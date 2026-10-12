import os, re
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from langchain_community.document_loaders import WebBaseLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document

load_dotenv()

SOURCES = [
    {"title": "GitLab - Time Off Types", "url": "https://handbook.gitlab.com/handbook/people-group/time-off-and-absence/time-off-types/", "country": "Global", "policy_type": "time_off"},
    {"title": "GitLab - Leave Types", "url": "https://handbook.gitlab.com/handbook/people-group/time-off-and-absence/leave-types/", "country": "Global", "policy_type": "leave"},
    {"title": "GitLab - US Leave of Absence", "url": "https://handbook.gitlab.com/handbook/people-policies/leave-of-absence/us", "country": "US", "policy_type": "leave"},
    {"title": "GitLab - Benefits", "url": "https://handbook.gitlab.com/handbook/total-rewards/benefits/general-and-entity-benefits/", "country": "Global", "policy_type": "benefits"},
    {"title": "GitLab - France Benefits", "url": "https://handbook.gitlab.com/handbook/total-rewards/benefits/general-and-entity-benefits/france-sas", "country": "France", "policy_type": "benefits"},
    {"title": "Amazon - Code of Conduct", "url": "https://ir.aboutamazon.com/corporate-governance/documents-charters/code-business-conduct-and-ethics", "country": "Global", "policy_type": "conduct"},
]

vector_store = None
answer_chain = None
status_message = "Not initialized"

def clean_text(text):
    text = re.sub(r"[ \\t]+", " ", text)
    text = re.sub(r"\\n\\s*\\n+", "\\n\\n", text)
    return text.strip()

def build_rag():
    documents = []
    for source in SOURCES:
        try:
            pages = WebBaseLoader(source["url"]).load()
            text = clean_text("\\n\\n".join(page.page_content for page in pages))
            if text:
                documents.append(Document(
                    page_content=text,
                    metadata={k: source[k] for k in ("title", "url", "country", "policy_type")}
                ))
                print("Loaded:", source["title"])
        except Exception as error:
            print("Could not load", source["title"], ":", error)

    if not documents:
        raise RuntimeError("No webpages loaded. Check internet and source URLs.")

    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    chunks = splitter.split_documents(documents)
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    store = FAISS.from_documents(chunks, embeddings)

    llm = ChatGroq(
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
        temperature=0.2,
        api_key=os.getenv("GROQ_API_KEY"),
    )
    prompt = ChatPromptTemplate.from_template(
        """You are an HR policy assistant. Answer only from the context.
Keep the answer clear and concise. Do not invent facts.
If the answer is missing, say: "I couldn't find that in the policy documents. Please contact HR."

Context:
{context}

Question:
{question}

Answer:"""
    )
    return store, prompt | llm | StrOutputParser(), len(chunks)

@asynccontextmanager
async def lifespan(app):
    global vector_store, answer_chain, status_message
    if not os.getenv("GROQ_API_KEY"):
        status_message = "Missing GROQ_API_KEY. Add it to .env."
    else:
        try:
            vector_store, answer_chain, count = build_rag()
            status_message = f"Ready. Indexed {count} chunks."
        except Exception as error:
            status_message = f"Initialization failed: {error}"
    print(status_message)
    yield

app = FastAPI(title="HR Policy Assistant API", lifespan=lifespan)

class QuestionRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)

@app.get("/")
def home():
    return {"message": "HR Policy Assistant API", "status": status_message}

@app.get("/health")
def health():
    ready = vector_store is not None and answer_chain is not None
    return {"status": "ready" if ready else "not_ready", "details": status_message}

@app.post("/ask")
def ask_question(request: QuestionRequest):
    if vector_store is None or answer_chain is None:
        raise HTTPException(status_code=503, detail=status_message)
    try:
        docs = vector_store.similarity_search(request.question, k=4)
        context = "\\n\\n".join(doc.page_content for doc in docs)
        answer = answer_chain.invoke({"context": context, "question": request.question})
        sources, seen = [], set()
        for doc in docs:
            url = doc.metadata.get("url", "")
            if url and url not in seen:
                seen.add(url)
                sources.append({"title": doc.metadata.get("title", "Policy source"), "url": url})
        return {"answer": answer, "sources": sources}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))

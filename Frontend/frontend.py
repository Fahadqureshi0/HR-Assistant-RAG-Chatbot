import requests
import streamlit as st

st.set_page_config(page_title="HR Policy Assistant", page_icon="📘")
st.title("📘 HR Policy Assistant")
st.caption("Ask questions about the connected HR policy webpages.")
st.info("Learning demo using GitLab policy webpages and Amazon's code of conduct. Check sources for official guidance.")

API_URL = "http://127.0.0.1:8000"

with st.sidebar:
    st.header("Backend")
    if st.button("Check backend status"):
        try:
            st.json(requests.get(f"{API_URL}/health", timeout=5).json())
        except requests.RequestException:
            st.error("Backend is not responding. Start backend.py first.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        for source in message.get("sources", []):
            st.markdown(f"- [{source['title']}]({source['url']})")

question = st.chat_input("Ask an HR policy question...")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Searching policy documents..."):
            try:
                response = requests.post(f"{API_URL}/ask", json={"question": question}, timeout=120)
                if response.ok:
                    result = response.json()
                    answer = result["answer"]
                    sources = result.get("sources", [])
                    st.markdown(answer)
                    if sources:
                        with st.expander("Sources"):
                            for source in sources:
                                st.markdown(f"- [{source['title']}]({source['url']})")
                    st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources})
                else:
                    st.error(response.json().get("detail", response.text))
            except requests.RequestException as error:
                st.error(f"Could not connect to backend: {error}")
                st.caption("Start it with: uvicorn backend:app --reload")

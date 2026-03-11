from src.providers import llm
response = llm.call(
  "Return OK in one sentence.",
  max_tokens=32,
  caller="sanity_check",
  )
print(response)
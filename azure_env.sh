# Source before running cooperbench so it uses LiteLLM's NATIVE azure route.
# Run models as:  -m azure/gpt-5.4   |  azure/gpt-5.4-mini  |  azure/gpt-5-nano
CWM=/Users/javieraguilarmartin1/Documents/repos/code-world-models/.env
export AZURE_API_KEY=$(grep '^AZURE_OPENAI_API_KEY=' "$CWM" | cut -d= -f2-)
export AZURE_API_BASE=$(grep '^AZURE_OPENAI_ENDPOINT=' "$CWM" | cut -d= -f2-)
export AZURE_API_VERSION=$(grep '^AZURE_OPENAI_API_VERSION=' "$CWM" | cut -d= -f2-)
# Override any stale AZURE_OPENAI_API_KEY exported by the shell profile (litellm falls back to it)
export AZURE_OPENAI_API_KEY="$AZURE_API_KEY"
# CRITICAL: unset endpoint so cooperbench's resolve_azure_config() returns None
# and the adapter keeps the native `azure/<deployment>` route instead of the
# broken openai-compatible rewrite.
unset AZURE_OPENAI_ENDPOINT

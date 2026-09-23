"""Provider factories reused from Coastworks 6dd244e; only supported providers are configured."""
from loguru import logger
from app.config import settings
from functools import lru_cache

@lru_cache
def get_llm():
    """
    Factory for LLM - returns LangChain chat model based on config.
    
    Supported providers: ollama, openai, anthropic, azure, gemini
    """
    provider = settings.LLM_PROVIDER
    logger.info(f"Initializing LLM provider: {provider}")
    
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required for OpenAI provider")
        return ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS
        )
    
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is required for Anthropic provider")
        return ChatAnthropic(
            model=settings.LLM_MODEL,
            api_key=settings.ANTHROPIC_API_KEY,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS
        )
    
    elif provider == "azure":
        from langchain_openai import AzureChatOpenAI
        if not settings.AZURE_OPENAI_ENDPOINT or not settings.AZURE_OPENAI_API_KEY:
            raise ValueError("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY are required")
        return AzureChatOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_deployment=settings.AZURE_OPENAI_DEPLOYMENT or settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS
        )

    elif provider == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            raise RuntimeError(
                "LLM_PROVIDER=gemini requires the declared langchain-google-genai package"
            ) from exc

        if not settings.GEMINI_API_KEY and not (
            settings.GEMINI_USE_VERTEX_AI and settings.GOOGLE_CLOUD_PROJECT
        ):
            raise ValueError(
                "GEMINI_API_KEY is required unless GEMINI_USE_VERTEX_AI and GOOGLE_CLOUD_PROJECT are configured"
            )

        kwargs = {
            "model": settings.LLM_MODEL,
            "temperature": settings.LLM_TEMPERATURE,
            "max_tokens": settings.LLM_MAX_TOKENS,
            "max_retries": 2,
        }
        if settings.GEMINI_USE_VERTEX_AI:
            kwargs.update({
                "vertexai": True,
                "project": settings.GOOGLE_CLOUD_PROJECT,
                "location": settings.GOOGLE_CLOUD_LOCATION,
            })
        else:
            kwargs["api_key"] = settings.GEMINI_API_KEY
        return ChatGoogleGenerativeAI(**kwargs)
    
    elif provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise RuntimeError(
                "LLM_PROVIDER=ollama requires the declared langchain-ollama package"
            ) from exc
        return ChatOllama(
            model=settings.LLM_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            temperature=settings.LLM_TEMPERATURE
        )
    
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")

@lru_cache
def get_embeddings():
    """
    Factory for embeddings - returns LangChain embeddings based on config.
    
    Supported providers: huggingface, openai, ollama, gemini
    """
    provider = settings.EMBEDDINGS_PROVIDER
    logger.info(f"Initializing embeddings provider: {provider}")
    
    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings")
        return OpenAIEmbeddings(
            model=settings.EMBEDDINGS_MODEL,
            api_key=settings.OPENAI_API_KEY
        )
    
    elif provider == "huggingface":
        from langchain_community.embeddings import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(
            model_name=settings.EMBEDDINGS_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True}
        )
    
    elif provider == "ollama":
        try:
            from langchain_ollama import OllamaEmbeddings
        except ImportError as exc:
            raise RuntimeError(
                "EMBEDDINGS_PROVIDER=ollama requires the declared langchain-ollama package"
            ) from exc
        return OllamaEmbeddings(
            model=settings.EMBEDDINGS_MODEL,
            base_url=settings.OLLAMA_BASE_URL
        )

    elif provider == "gemini":
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
        except ImportError as exc:
            raise RuntimeError(
                "EMBEDDINGS_PROVIDER=gemini requires the declared langchain-google-genai package"
            ) from exc

        if not settings.GEMINI_API_KEY and not (
            settings.GEMINI_USE_VERTEX_AI and settings.GOOGLE_CLOUD_PROJECT
        ):
            raise ValueError(
                "GEMINI_API_KEY is required unless GEMINI_USE_VERTEX_AI and GOOGLE_CLOUD_PROJECT are configured"
            )

        kwargs = {"model": settings.EMBEDDINGS_MODEL}
        if settings.GEMINI_USE_VERTEX_AI:
            kwargs.update({
                "vertexai": True,
                "project": settings.GOOGLE_CLOUD_PROJECT,
                "location": settings.GOOGLE_CLOUD_LOCATION,
            })
        else:
            kwargs["api_key"] = settings.GEMINI_API_KEY
        return GoogleGenerativeAIEmbeddings(**kwargs)
    
    else:
        raise ValueError(f"Unknown embeddings provider: {provider}")
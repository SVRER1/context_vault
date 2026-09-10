from contextvault.llm.client import LLMClient
from contextvault.llm.schemas import IntentClassification
from contextvault.llm.prompts import INTENT_PROMPT

class IntentRouter:
    """Routes user input to the appropriate agent capability."""
    
    @staticmethod
    def classify(user_input: str, llm_client: LLMClient = None) -> IntentClassification:
        lower_input = user_input.lower().strip()
        
                                          
        if any(w in lower_input for w in ["duplicate", "dupes", "same file", "identical"]):
            return IntentClassification(intent="duplicates", confidence=0.95, parameters={})
            
                                          
        if any(w in lower_input for w in [
            "generate", "study guide", "flashcard", "flashcards", "quiz", 
            "revision notes", "summarize", "summary", "timeline", "vault report"
        ]):
            return IntentClassification(intent="generate", confidence=0.9, parameters={"query": user_input})
            
                                            
        if any(w in lower_input for w in ["organise", "organize", "restructure", "categorize", "sort files"]):
            return IntentClassification(intent="organise", confidence=0.9, parameters={})

                                        
        if any(w in lower_input for w in [
            "what can you do", "what can the agent do", "capabilities",
            "capability report", "tooling", "available tools", "tools available",
        ]):
            return IntentClassification(intent="capabilities", confidence=0.98, parameters={})
            
                                      
        if any(w in lower_input for w in ["status", "how many files", "vault health", "vault info", "overview"]):
            return IntentClassification(intent="status", confidence=0.9, parameters={})
            
                   
        if any(w in lower_input for w in ["search", "find", "where is", "where are", "look up"]):
            return IntentClassification(intent="search", confidence=0.85, parameters={"query": user_input})
            
                                                                        
        if llm_client and llm_client.is_available():
            try:
                return llm_client.generate_structured(
                    prompt=INTENT_PROMPT.format(user_input=user_input),
                    system="You are an intent classification system.",
                    schema=IntentClassification
                )
            except Exception:
                pass
                
                                          
        return IntentClassification(intent="rag_query", confidence=0.5, parameters={"query": user_input})

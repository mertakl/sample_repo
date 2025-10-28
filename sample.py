import logging
import json
import time
from datetime import datetime
from typing import Optional, Dict, Any
import uuid

class KibanaLogger:
    """
    Logger for sending structured logs to Kibana/Elasticsearch via LAAS (Kafka)
    Assumes enable_laas_client() has already been called in Django settings
    """
    
    def __init__(self, logger_name: str = "yara_eureka", log_level: str = "INFO"):
        # Just get the logger - LAAS is already configured via Django settings
        self.logger = logging.getLogger(logger_name)
        
        # Allow configuration of log level
        level = getattr(logging, log_level.upper(), logging.INFO)
        self.logger.setLevel(level)
    
    def _log_metric(self, event_type: str, data: Dict[str, Any]):
        """Base method to log structured metrics"""
        log_entry = {
            "event_type": event_type,
            **data
        }
        self.logger.info(json.dumps(log_entry))
    
    # ===== REQUEST METRICS =====
    
    def log_request(self, segment: str, amw_rights: str, conversation_id: str):
        """Log each API request with segment and AMW rights"""
        self._log_metric("api_request", {
            "segment": segment,
            "amw_rights": amw_rights,
            "conversation_id": conversation_id
        })
    
    def log_user_query(self, query: str, conversation_id: str, 
                       conversation_length: int):
        """Log user query details"""
        self._log_metric("user_query", {
            "conversation_id": conversation_id,
            "query_size_chars": len(query),
            "query_size_tokens": self._estimate_tokens(query),
            "conversation_length": conversation_length
        })
    
    # ===== TIMING METRICS =====
    
    def log_total_response_time(self, duration_ms: float, 
                                conversation_id: str):
        """Log total API response handling time"""
        self._log_metric("response_time_total", {
            "duration_ms": duration_ms,
            "conversation_id": conversation_id
        })
    
    def log_lexical_retrieval_time(self, duration_ms: float, 
                                   conversation_id: str):
        """Log lexical DB retrieval time"""
        self._log_metric("retrieval_time_lexical", {
            "duration_ms": duration_ms,
            "conversation_id": conversation_id
        })
    
    def log_semantic_retrieval_time(self, duration_ms: float, 
                                    conversation_id: str):
        """Log semantic DB retrieval time"""
        self._log_metric("retrieval_time_semantic", {
            "duration_ms": duration_ms,
            "conversation_id": conversation_id
        })
    
    def log_reranking_time(self, duration_ms: float, conversation_id: str,
                          reranking_scores: Optional[list] = None):
        """Log reranking API call time"""
        data = {
            "duration_ms": duration_ms,
            "conversation_id": conversation_id
        }
        if reranking_scores:
            data["reranking_scores"] = reranking_scores
        self._log_metric("reranking_time", data)
    
    def log_llm_response_time(self, duration_ms: float, conversation_id: str,
                             model_name: str):
        """Log LLM API call time-to-response"""
        self._log_metric("llm_response_time", {
            "duration_ms": duration_ms,
            "conversation_id": conversation_id,
            "model_name": model_name
        })
    
    def log_guardrails_latency(self, guardrail_type: str, duration_ms: float,
                               conversation_id: str):
        """Log input/output guardrails latency"""
        self._log_metric("guardrails_latency", {
            "guardrail_type": guardrail_type,  # "input" or "output"
            "duration_ms": duration_ms,
            "conversation_id": conversation_id
        })
    
    # ===== MODEL API CALL COUNTS =====
    
    def log_embedding_call(self, call_type: str, model_name: str,
                          conversation_id: str, num_items: int = 1):
        """Log embedding model API calls (query or passage)"""
        self._log_metric("embedding_api_call", {
            "call_type": call_type,  # "query" or "passage"
            "model_name": model_name,
            "conversation_id": conversation_id,
            "num_items": num_items
        })
    
    def log_llm_call(self, model_name: str, conversation_id: str,
                    prompt_size: Optional[int] = None):
        """Log LLM model API calls"""
        data = {
            "model_name": model_name,
            "conversation_id": conversation_id
        }
        if prompt_size:
            data["prompt_size_tokens"] = prompt_size
        self._log_metric("llm_api_call", data)
    
    def log_reranking_call(self, model_name: str, conversation_id: str,
                          num_documents: int):
        """Log reranking model API calls"""
        self._log_metric("reranking_api_call", {
            "model_name": model_name,
            "conversation_id": conversation_id,
            "num_documents": num_documents
        })
    
    # ===== DOCUMENT & PARSING METRICS =====
    
    def log_document_parsing(self, source: str, document_name: str,
                            status: str, error_message: Optional[str] = None):
        """Log document parsing success/failure"""
        data = {
            "source": source,  # "KBM" or "Eureka"
            "document_name": document_name,
            "status": status,  # "success", "failed", "invalid_format"
        }
        if error_message:
            data["error_message"] = error_message
        self._log_metric("document_parsing", data)
    
    def log_caption_generation(self, status: str, document_name: str,
                              error_message: Optional[str] = None):
        """Log caption generation attempts"""
        data = {
            "document_name": document_name,
            "status": status  # "success" or "failed"
        }
        if error_message:
            data["error_message"] = error_message
        self._log_metric("caption_generation", data)
    
    # ===== RESPONSE METRICS =====
    
    def log_response(self, response_type: str, response_size: int,
                    conversation_id: str, confidence_grade: str,
                    confidence_score: Optional[Dict] = None):
        """Log response details"""
        data = {
            "response_type": response_type,
            "response_size_chars": response_size,
            "conversation_id": conversation_id,
            "confidence_grade": confidence_grade  # "low", "medium", "high"
        }
        if confidence_score:
            data["confidence_score"] = confidence_score
        self._log_metric("response_details", data)
    
    def log_guardrail_trigger(self, trigger_type: str, conversation_id: str,
                             message_type: str):
        """Log guardrail triggers"""
        self._log_metric("guardrail_trigger", {
            "trigger_type": trigger_type,
            "conversation_id": conversation_id,
            "message_type": message_type  # "user" or "assistant"
        })
    
    def log_eureka_interaction(self, interaction_type: str, 
                              conversation_id: str):
        """Log Eureka API interactions"""
        self._log_metric("eureka_interaction", {
            "interaction_type": interaction_type,
            "conversation_id": conversation_id
        })
    
    # ===== HELPER METHODS =====
    
    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimation (adjust based on your tokenizer)"""
        return len(text.split())
    
    @staticmethod
    def generate_conversation_id() -> str:
        """Generate unique conversation ID"""
        return str(uuid.uuid4())


# ===== USAGE EXAMPLE =====

class YaraEurekaAPI:
    """Example integration in your API"""
    
    def __init__(self):
        # LAAS is already enabled in Django settings, just initialize logger
        self.logger = KibanaLogger()
    
    def handle_request(self, user_query: str, segment: str, amw_rights: str,
                      conversation_history: list):
        conversation_id = self.logger.generate_conversation_id()
        
        # Log the request
        self.logger.log_request(segment, amw_rights, conversation_id)
        
        # Log user query
        self.logger.log_user_query(
            user_query, 
            conversation_id,
            len(conversation_history)
        )
        
        # Track total response time
        start_time = time.time()
        
        # Input guardrails
        guard_start = time.time()
        self._check_input_guardrails(user_query)
        self.logger.log_guardrails_latency(
            "input",
            (time.time() - guard_start) * 1000,
            conversation_id
        )
        
        # Lexical retrieval
        lex_start = time.time()
        lexical_results = self._lexical_search(user_query)
        self.logger.log_lexical_retrieval_time(
            (time.time() - lex_start) * 1000,
            conversation_id
        )
        
        # Semantic retrieval
        sem_start = time.time()
        # Log embedding call for query
        self.logger.log_embedding_call(
            "query", "text-embedding-model", conversation_id
        )
        semantic_results = self._semantic_search(user_query)
        self.logger.log_semantic_retrieval_time(
            (time.time() - sem_start) * 1000,
            conversation_id
        )
        
        # Reranking
        rerank_start = time.time()
        reranked_docs, scores = self._rerank_documents(
            lexical_results + semantic_results
        )
        self.logger.log_reranking_call(
            "reranker-model", conversation_id, len(reranked_docs)
        )
        self.logger.log_reranking_time(
            (time.time() - rerank_start) * 1000,
            conversation_id,
            scores
        )
        
        # LLM call
        llm_start = time.time()
        self.logger.log_llm_call(
            "gpt-4", conversation_id, 
            prompt_size=len(user_query.split())
        )
        response = self._generate_llm_response(user_query, reranked_docs)
        self.logger.log_llm_response_time(
            (time.time() - llm_start) * 1000,
            conversation_id,
            "gpt-4"
        )
        
        # Output guardrails
        guard_out_start = time.time()
        self._check_output_guardrails(response)
        self.logger.log_guardrails_latency(
            "output",
            (time.time() - guard_out_start) * 1000,
            conversation_id
        )
        
        # Log response details
        self.logger.log_response(
            response.response_type,
            len(response.text),
            conversation_id,
            response.confidence_grade,
            {
                "contradictions": response.contradictions_score,
                "judge_metric": response.judge_metric
            }
        )
        
        # Log total time
        self.logger.log_total_response_time(
            (time.time() - start_time) * 1000,
            conversation_id
        )
        
        return response
    
    def _check_input_guardrails(self, text):
        pass  # Your implementation
    
    def _lexical_search(self, query):
        pass  # Your implementation
    
    def _semantic_search(self, query):
        pass  # Your implementation
    
    def _rerank_documents(self, docs):
        pass  # Your implementation
    
    def _generate_llm_response(self, query, docs):
        pass  # Your implementation
    
    def _check_output_guardrails(self, response):
        pass  # Your implementation

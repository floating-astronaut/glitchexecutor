"""
GlitchExecutor Ensemble Engine - Sentiment Analysis (Model 8)
News sentiment via LLM - runs every 30 minutes per symbol.
"""
import os
import json
import logging
import requests
from typing import Dict, Optional

logger = logging.getLogger("SentimentModel")


class SentimentAnalyzer:
    """
    Model 8: News Sentiment Analysis via LLM.
    Fetches news and analyzes sentiment using Claude or OpenAI.
    """
    
    name = "sentiment"
    version = "1.0"
    
    def __init__(self, api_key: str = None, provider: str = "anthropic"):
        """
        Initialize sentiment analyzer.

        Args:
            api_key: LLM API key (defaults to SENTIMENT_LLM_KEY env var)
            provider: 'anthropic', 'openai', or 'vertex'
        """
        self.api_key = api_key or os.environ.get("SENTIMENT_LLM_KEY", "")
        self.provider = provider.lower()

        # Vertex AI doesn't need an API key — uses ADC (Application Default Credentials)
        if self.provider == "vertex":
            self.gcp_project = os.environ.get("GCP_PROJECT", "")
            self.gcp_location = os.environ.get("GCP_LOCATION", "us-central1")
            if self.gcp_project:
                logger.info(f"Vertex AI Gemini enabled (project={self.gcp_project})")
            else:
                logger.warning("Vertex AI: GCP_PROJECT not set")
        elif not self.api_key:
            logger.warning("No API key provided - sentiment analysis disabled")
    
    def _fetch_crypto_news(self, symbol: str) -> list:
        """
        Fetch recent crypto news headlines.
        Uses CryptoPanic API or falls back to RSS feeds.
        """
        headlines = []
        
        # Try CryptoPanic API (free tier available)
        try:
            # Extract base currency (e.g., BTC from BTCUSD)
            base = symbol[:3] if len(symbol) >= 6 else symbol
            
            # CryptoPanic doesn't need API key for public endpoint
            url = f"https://cryptopanic.com/api/v1/posts/"
            params = {
                "auth_token": os.environ.get("CRYPTOPANIC_API_KEY", ""),
                "currencies": base,
                "public": "true",
                "limit": 10
            }
            
            # If no auth token, skip CryptoPanic
            if params["auth_token"]:
                resp = requests.get(url, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    for post in data.get("results", []):
                        headlines.append(post.get("title", ""))
            
        except Exception as e:
            logger.debug(f"CryptoPanic fetch failed: {e}")
        
        # Fallback to RSS feeds
        if not headlines:
            try:
                # CoinDesk RSS
                rss_urls = [
                    "https://www.coindesk.com/arc/outboundfeeds/rss/",
                ]
                
                # Try to fetch and parse RSS (simplified - just use feedparser if available)
                try:
                    import feedparser
                    for url in rss_urls:
                        feed = feedparser.parse(url)
                        for entry in feed.entries[:5]:
                            title = entry.get("title", "")
                            if any(term in title.lower() for term in [symbol.lower()[:3], "bitcoin", "crypto"]):
                                headlines.append(title)
                except ImportError:
                    pass
                    
            except Exception as e:
                logger.debug(f"RSS fetch failed: {e}")
        
        # If still no headlines, use mock data for testing
        if not headlines:
            logger.warning("No news fetched - using mock headlines for testing")
            headlines = [
                f"{symbol} shows strong momentum in current market conditions",
                "Crypto markets remain volatile ahead of Fed decision",
                f"Analysts predict continued growth for {symbol[:3]}",
                "Institutional investors increasing crypto allocations",
                "Market sentiment remains cautiously optimistic"
            ]
        
        return headlines[:10]  # Limit to 10 headlines
    
    def _is_openrouter_key(self) -> bool:
        """Detect if the API key is an OpenRouter key."""
        return self.api_key.startswith("sk-or-")

    def _analyze_with_llm(self, symbol: str, headlines: list) -> Dict:
        """Send headlines to LLM for sentiment analysis."""

        prompt = f"""You are a financial news sentiment analyzer. Given these headlines about {symbol}, return ONLY a JSON object with:
- "direction": "bullish" | "bearish" | "neutral"
- "score": float from -1.0 (extremely bearish) to 1.0 (extremely bullish)
- "reasoning": one sentence summary

Headlines:
{chr(10).join(f"- {h}" for h in headlines)}

Respond with ONLY valid JSON, no other text."""

        try:
            if self.provider == "vertex":
                return self._call_vertex(prompt)
            elif self._is_openrouter_key():
                return self._call_openrouter(prompt)
            elif self.provider == "anthropic":
                return self._call_anthropic(prompt)
            elif self.provider == "openai":
                return self._call_openai(prompt)
            else:
                logger.error(f"Unknown provider: {self.provider}")
                return self._fallback_sentiment()

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return self._fallback_sentiment()

    def _call_vertex(self, prompt: str) -> Dict:
        """Call Google Gemini API (generativelanguage endpoint)."""
        gemini_key = os.environ.get("GEMINI_API_KEY", self.api_key)
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{model}:generateContent?key={gemini_key}"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 500, "responseMimeType": "application/json"},
            "systemInstruction": {
                "parts": [{"text": "You are a financial sentiment analyzer. Return only valid JSON."}]
            },
        }

        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        content = ""
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                content += part.get("text", "")

        return self._parse_llm_response(content)

    def _call_openrouter(self, prompt: str) -> Dict:
        """Call OpenRouter API (OpenAI-compatible)."""
        import openai

        client = openai.OpenAI(
            api_key=self.api_key,
            base_url="https://openrouter.ai/api/v1"
        )

        response = client.chat.completions.create(
            model="anthropic/claude-3-haiku",
            max_tokens=150,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "You are a financial sentiment analyzer. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ]
        )

        content = response.choices[0].message.content if response.choices else "{}"
        return self._parse_llm_response(content)

    def _call_anthropic(self, prompt: str) -> Dict:
        """Call Anthropic Claude API."""
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)

        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=150,
            temperature=0.1,
            system="You are a financial sentiment analyzer. Return only valid JSON.",
            messages=[{"role": "user", "content": prompt}]
        )

        content = response.content[0].text if response.content else "{}"
        return self._parse_llm_response(content)

    def _call_openai(self, prompt: str) -> Dict:
        """Call OpenAI API."""
        import openai

        client = openai.OpenAI(api_key=self.api_key)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=150,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "You are a financial sentiment analyzer. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ]
        )

        content = response.choices[0].message.content if response.choices else "{}"
        return self._parse_llm_response(content)
    
    def _parse_llm_response(self, content: str) -> Dict:
        """Parse LLM JSON response."""
        try:
            # Extract JSON from potential markdown
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            result = json.loads(content)
            
            # Validate required fields
            if "direction" not in result or "score" not in result:
                raise ValueError("Missing required fields")
            
            # Normalize direction
            result["direction"] = result["direction"].lower()
            if result["direction"] not in ["bullish", "bearish", "neutral"]:
                result["direction"] = "neutral"
            
            # Clamp score
            result["score"] = max(-1.0, min(1.0, float(result["score"])))
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return self._fallback_sentiment()
    
    def _fallback_sentiment(self) -> Dict:
        """Return neutral sentiment when LLM fails."""
        return {
            "direction": "neutral",
            "score": 0.0,
            "reasoning": "Sentiment analysis unavailable"
        }
    
    def analyze(self, symbol: str) -> Dict:
        """
        Run sentiment analysis for a symbol.
        
        Returns dict with:
        - direction: bullish/bearish/neutral
        - score: -1.0 to 1.0
        - reasoning: explanation string
        """
        if not self.api_key:
            logger.warning("No API key - returning neutral sentiment")
            return self._fallback_sentiment()
        
        logger.info(f"Analyzing sentiment for {symbol}")
        
        # Fetch news
        headlines = self._fetch_crypto_news(symbol)
        logger.debug(f"Fetched {len(headlines)} headlines for {symbol}")
        
        # Analyze with LLM
        result = self._analyze_with_llm(symbol, headlines)
        
        logger.info(f"Sentiment for {symbol}: {result['direction']} (score: {result['score']})")
        
        return result

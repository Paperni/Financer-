from textblob import TextBlob
import re

class QualitativeIntelligence:
    def __init__(self, text_10k):
        self.text = text_10k
        self.blob = TextBlob(text_10k) if text_10k else None

    def analyze_simplicity(self):
        """
        Simplicity Score based on average sentence length.
        Lower is better (easier to understand).
        Returns classification: 'Simple', 'Moderate', 'Complex'
        """
        if not self.blob:
            return "Unknown"
        
        avg_len = sum(len(s.words) for s in self.blob.sentences) / len(self.blob.sentences)
        
        if avg_len < 15:
            return "Simple (Business model likely easy to understand)"
        elif avg_len < 25:
            return "Moderate"
        else:
            return "Complex (Warning: High cognitive load)"

    def analyze_moat(self):
        """
        Scans for Moat-related keywords.
        Returns a dictionary of potential moats found.
        """
        if not self.text:
            return {}
        
        moats = {
            "Network Effect": ["network effect", "viral", "platform", "ecosystem", "user base"],
            "Switching Costs": ["switching cost", "retention", "locked in", "integration", "high cost to change"],
            "Cost Advantage": ["economies of scale", "low cost producer", "proprietary technology", "vertical integration"],
            "Intangibles": ["brand power", "patent", "trademark", "customer loyalty", "reputation"]
        }
        
        found_moats = {}
        text_lower = self.text.lower()
        
        for category, keywords in moats.items():
            count = 0
            for keyword in keywords:
                count += text_lower.count(keyword)
            
            if count > 0:
                found_moats[category] = "Strong" if count > 10 else "Potential"
        
        return found_moats

    def analyze_management(self):
        """
        Integrity Check: Sentiment Analysis of the text.
        Returns 'Optimistic', 'Neutral', or 'Pessimistic'
        """
        if not self.blob:
            return "Unknown"
            
        sentiment = self.blob.sentiment.polarity
        
        if sentiment > 0.1:
            return "Optimistic (Management seems confident)"
        elif sentiment < -0.05:
            return "Pessimistic (Management tone is cautious/negative)"
        else:
            return "Neutral/Balanced"

if __name__ == "__main__":
    # Test
    sample_text = "Apple operates a global ecosystem. The network effect is strong. Users face high switching costs due to integration."
    qi = QualitativeIntelligence(sample_text)
    print("Simplicity:", qi.analyze_simplicity())
    print("Moats:", qi.analyze_moat())
    print("Management:", qi.analyze_management())

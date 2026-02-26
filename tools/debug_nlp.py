from textblob import TextBlob

text = "This is a simple sentence. This is another one."
try:
    sentences = TextBlob(text[:50000]).sentences
    avg_len = sum(len(s.words) for s in sentences) / max(1, len(sentences))
    print(f"Avg len: {avg_len}")
    
    blob = TextBlob(text[:10000])
    print(f"Sentiment: {blob.sentiment.polarity}")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

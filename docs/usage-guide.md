# Usage Guide: When to Use Agentic Batch Processor

## The Golden Rule

**Use Agentic Batch Processor when each work unit requires LLM reasoning/intelligence.**

**Don't use it when the task is deterministic - just generate a Python script instead.**

## Decision Tree

```
Does your task involve bulk processing?
│
├─ NO → Just use LLM directly - not a bulk task
│
└─ YES → Does EACH item need LLM intelligence?
         │
         ├─ YES → USE AGENTIC BATCH PROCESSOR
         │        Examples:
         │        • Analyze image content
         │        • Review code for bugs
         │        • Extract entities from text
         │        • Classify/categorize content
         │        • Generate creative outputs
         │
         └─ NO → DON'T USE - Generate a Python script instead
                  Examples:
                  • Rotate images
                  • Convert file formats
                  • Rename files by pattern
                  • Filter CSV data
```

## Real-World Examples

### Example 1: Image Object Detection (Good Use Case)

**Request:** "Identify all objects in these images and save to CSV"

**Why Agentic Batch Processor?**
- Each image needs vision model analysis ✓
- LLM must identify/categorize objects ✓
- Smart CSV updating (check duplicates, increment counts) ✓
- Can't be scripted - requires visual understanding ✓

**How it works:**
1. Orchestrator enumerates images
2. Generates prompt: "Analyze {file_path}, identify objects, update CSV"
3. Each worker LLM:
   - Uses vision to see the image
   - Identifies objects
   - Reads CSV, checks for duplicates
   - Updates CSV intelligently

### Example 2: Code Security Review (Good Use Case)

**Request:** "Review all Python files for security vulnerabilities"

**Why Agentic Batch Processor?**
- Each file needs code understanding ✓
- LLM must reason about security implications ✓
- Context-aware analysis (different patterns per file) ✓
- Can't use regex - needs semantic understanding ✓

**How it works:**
1. Orchestrator finds all `.py` files
2. Generates prompt: "Review {file_path} for SQL injection, XSS, etc."
3. Each worker LLM:
   - Reads and understands code
   - Identifies potential vulnerabilities
   - Explains why each is a risk
   - Suggests fixes

### Example 3: Document Data Extraction (Good Use Case)

**Request:** "Extract company names, dates, and dollar amounts from contracts"

**Why Agentic Batch Processor?**
- Unstructured documents (no fixed format) ✓
- LLM must understand context ✓
- Ambiguous entity recognition ✓
- Different document structures ✓

**How it works:**
1. Orchestrator finds all contract PDFs
2. Generates prompt: "Extract entities from {file_path}, output JSON"
3. Each worker LLM:
   - Reads document
   - Identifies entities using language understanding
   - Determines relationships
   - Outputs structured data

### Example 4: Image Rotation (Bad Use Case)

**Request:** "Rotate all images 90 degrees clockwise"

**Why NOT Agentic Batch Processor?**
- Rotation is deterministic ✗
- Same operation on every image ✗
- No reasoning needed ✗
- Can be done with 10 lines of Python ✗

**Better approach:**
Have orchestrator LLM generate:
```python
from PIL import Image
from pathlib import Path

for img_path in Path("/images").glob("**/*.jpg"):
    img = Image.open(img_path)
    rotated = img.rotate(-90, expand=True)
    rotated.save(img_path)
    print(f"Rotated {img_path}")
```

### Example 5: File Renaming (Bad Use Case)

**Request:** "Rename all files to lowercase"

**Why NOT Agentic Batch Processor?**
- Simple string operation ✗
- No reasoning needed ✗
- Deterministic algorithm ✗

**Better approach:**
```python
from pathlib import Path

for file_path in Path("/files").rglob("*"):
    if file_path.is_file():
        new_name = file_path.name.lower()
        file_path.rename(file_path.parent / new_name)
```

### Example 6: Review Theme Clustering (Good Use Case)

**Request:** "Analyze product reviews and identify main themes for each product"

**Why Agentic Batch Processor?**
- Semantic understanding of review content ✓
- Theme identification requires reasoning ✓
- Contextual clustering (not keyword matching) ✓
- Sentiment analysis per theme ✓
- Each product's reviews are unique ✓

**How it works:**
1. Work units = Products (100 products)
2. Each worker queries database for their product's reviews
3. Worker LLM analyzes all reviews semantically
4. Identifies 5-7 themes with sentiment and representative quotes
5. Saves structured JSON output

**Example output:**
```json
{
  "product_id": "prod_123",
  "themes": [
    {
      "theme_name": "battery life",
      "mention_count": 45,
      "sentiment": "negative",
      "quotes": ["Battery drains too fast...", "Only lasts 4 hours..."]
    },
    {
      "theme_name": "screen quality",
      "mention_count": 32,
      "sentiment": "positive",
      "quotes": ["Beautiful display...", "Colors are vibrant..."]
    }
  ]
}
```

**Value:** 8 workers process 100 products in parallel → ~12x faster than sequential processing

## Cost Considerations

### Agentic Batch Processor Costs

Each work unit spawns a **full agentic session**, not just a single API call:
- Agents may make multiple LLM calls per unit (tool use, reasoning, retries)
- Token usage varies significantly based on task complexity
- Context grows with each turn in a session
- Error recovery and retries add additional calls

**Worth it for:** Tasks requiring intelligence (analysis, understanding, reasoning)
**Not worth it for:** Tasks solvable with code (transformations, conversions)

### Script Generation Costs

A single LLM call generates a script that runs deterministically on all files.

**Always prefer** script generation for deterministic tasks!

## Hybrid Approach

Sometimes you need **both**:

**Example:** "Analyze images for inappropriate content, blur faces, and resize to 1024x1024"

**Optimal split:**
1. **Agent Swarm:** Content moderation (needs LLM vision + reasoning)
   - Each worker analyzes image
   - Outputs: `{"safe": true/false, "reasons": [...]}`

2. **Python Script:** Blur + resize (deterministic)
   - Orchestrator generates script
   - Script processes only images flagged as needing blurring
   - Resizes all images

## Quick Checklist

Before using Agentic Batch Processor, ask yourself:

- [ ] Does each item need independent analysis/understanding?
- [ ] Would the logic change based on content (not just metadata)?
- [ ] Is it impossible/impractical to write rules for this?
- [ ] Does it involve vision, language understanding, or reasoning?
- [ ] Am I okay with LLM API costs per item?

**5/5 YES** → Agentic Batch Processor is perfect!
**3-4/5 YES** → Probably worth it, consider carefully
**1-2/5 YES** → Generate a script instead
**0/5 YES** → Definitely just generate a script

## Summary

| Task Type | Use Agentic Batch Processor? | Why |
|-----------|------------------------------|-----|
| Image analysis | YES | Requires vision model per image |
| Content moderation | YES | Requires understanding context |
| Code review | YES | Requires semantic code analysis |
| Data extraction | YES | Unstructured input, needs reasoning |
| Translation | YES | Context-aware language understanding |
| Sentiment analysis | YES | Requires text comprehension |
| Review clustering | YES | Semantic theme identification |
| Ticket categorization | YES | Context-aware classification |
| Churn prediction | YES | Pattern recognition in communications |
| Image rotation | NO | Deterministic transformation |
| File renaming | NO | Pattern-based, no reasoning |
| Format conversion | NO | Mechanical transformation |
| CSV filtering | NO | Rule-based logic |

**Remember:** Agentic Batch Processor is powerful but expensive. Use it when you need intelligence, not when you need processing power.

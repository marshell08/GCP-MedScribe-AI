import re
with open('static/index.html', 'r') as f:
    content = f.read()

jsmatch = re.search(r'<script>(.*?)</script>', content, re.DOTALL)
if jsmatch:
    js = jsmatch.group(1)
    # simple bracket counter
    curl_open = js.count('{')
    curl_close = js.count('}')
    paren_open = js.count('(')
    paren_close = js.count(')')
    print(f"Braces: {curl_open} open, {curl_close} closed. Diff: {curl_open - curl_close}")
    print(f"Parens: {paren_open} open, {paren_close} closed. Diff: {paren_open - paren_close}")
else:
    print("No script found")

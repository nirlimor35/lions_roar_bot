
from datetime import datetime

text = (
    "This is message 1. This is message 2. This is message 3"
)
now = datetime.now()
top = ".".join(text.split(".")[:-1])
bottom = text.split(".")[-1].strip()

print(top + "\n\n" + f"{now} - {bottom}")
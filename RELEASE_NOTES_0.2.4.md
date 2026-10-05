# CutData AI 0.2.4

- Pass-plan stages now scale RPM and feed together when a machine or requested limit applies, so each stage keeps the feed per tooth/rev the AI chose.
- A Guided result whose independent check did not complete is no longer cached; repeating the calculation retries the check. Older cached results in that state are ignored.
- RPM/feed limit messages name the machine when its limit, not the entered maximum, was the one applied.

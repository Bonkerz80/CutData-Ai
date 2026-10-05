# CutData AI 0.2.2

- Calculation status now shows the current stage and elapsed time, including research and independent checking.
- Removed automatic SDK retries that could turn each 90-second AI request into several silent minutes. A timed-out research request now gives a clear message; a timed-out independent check returns the recommendation marked unverified.
- The app records separate research and check durations with response usage diagnostics.
- Settings explains that Maximum reasoning can be substantially slower. No saved model or reasoning preference is changed automatically.

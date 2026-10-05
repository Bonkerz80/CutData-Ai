# CutData AI 0.2.1

- The selected AI model is visible in the main window, including in Mock and No API Key modes.
- Changing the model in Settings immediately explains that Save is required to apply it.
- Fixed the Settings save path so the main window actually refreshes after the dialog closes.
- Settings provides a Save & Restart App action. Ordinary Save confirms the selected model and offers a restart button; live AI uses the saved model immediately.
- A cancelled calculation can be restarted. If the previous request is still finishing, the restart is queued and clearly shown.

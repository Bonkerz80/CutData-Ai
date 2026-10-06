# CutData AI 0.2.7

- Fixed "AI-guided result must include a pass count and at least one pass-plan stage". The AI is allowed to leave the pass count empty when it is not meaningful, as it does for drilling, reaming and tapping, but the app then rejected the answer. A missing pass count is now counted from the pass plan. For a drill, reamer or tap answer with no pass plan, a single stage is shown using the AI's own RPM and feed. A milling answer with no pass plan is still rejected.

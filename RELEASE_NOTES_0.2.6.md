# CutData AI 0.2.6

The Guided form now shows the boxes that belong to the selected tool. The AI instructions and cached results are unchanged.

- **Tool material** and **Coating** appear under the tool selector for a library tool. They start from the Tool Library record and reset when a different tool is picked. A change applies to that calculation only; the library record is not altered. Insert cutters do not show them, because the linked insert decides grade and coating.
- Drills have a **Pilot hole diameter** box (0 = drilling from solid). It must be smaller than the drill, is sent to the AI and the independent check as a hole that is only being opened out, and shows in Recent.
- Each tool shows only its own boxes:
  - Drill: hole depth, through/blind, pilot hole diameter.
  - Reamer: hole depth, through/blind, existing hole diameter.
  - Tap: thread size, pitch, thread depth, through/blind, cutting/form tap.
  - Thread mill: thread size, pitch, thread depth, through/blind, existing hole diameter, entry access.
  - Chamfer / countersink: chamfer size, hole diameter to chamfer.
  - Milling cutters: unchanged, by job type.
- "Required hole diameter" is no longer asked for drills, reamers and taps (the tool sets it), and entry access is no longer asked for drilling, reaming and tapping.
- Picking a tap or thread mill fills **Thread size** and **Pitch**. The size comes from the library record, then from a size written in the tool's name or code (for example "M10x1.25"), then from its diameter. A missing pitch uses the standard metric coarse pitch. Both stay editable, and typing a size by hand sets the coarse pitch.
- Taps and thread mills in the Tool Library have **Thread size** and **Thread pitch** fields, in Add tool and in Edit.
- **From Tool Library** in Advanced / Manual also fills thread size and pitch for a tap.
- The new boxes are remembered between sessions and refilled when a recent Guided calculation is reopened.

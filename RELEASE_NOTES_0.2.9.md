# CutData AI 0.2.9

Tool Library overhaul. Stored tools, inserts and workshop notes are kept as they are.

- **Edit in place.** The library lists tools on the left and shows the selected one on the right. A change saves when you leave the box, pick another record or close the window; looking at a record without changing it writes nothing.
- **Only the boxes for the tool type.** A drill shows diameter, material, coating, flute length, point angle and usual stickout; a tap shows thread size, pitch, cutting/form, material and coating; insert cutters show number of tips and the linked insert. Boxes that do not apply are hidden and keep whatever was stored.
- **Pick lists instead of typing.** Tool material and coating are the same lists used on the Guided form, numbers are number boxes, and Manufacturer offers the makers already in the library. A recorded value that is not in a list is kept.
- **Starting values for new tools.** A new tool starts with typical values for its type (for example 4 flutes and carbide for an end mill, HSS and a 118° point for a drill, ball radius as half the diameter) and is no longer marked "needs review" automatically. A tap fills pitch from the thread size.
- **Automatic names.** A new tool is named from its details, such as "20mm HSS-Co Drill", "M10 x 1.5 HSS Tap" or "16mm 4-Flute Carbide End Mill". Typing your own name keeps it; existing names are not changed.
- **Catalogue details tucked away.** Part numbers, shank and overall length, source and confidence are in a collapsed section.
- **Fewer buttons.** ADD (tool, set of tools, insert, or look one up with AI), DUPLICATE and DELETE. LOOK UP WITH AI and WORKSHOP NOTES sit under the selected record.
- **Find tools faster.** A type filter (drills, taps and thread mills, reamers, end mills, chamfer tools, insert cutters) beside the search box, and Type, Size, Material, Coating and Review columns that sort when the heading is clicked. Size sorts by diameter.
- **Add a set.** Enter the type, material and coating once and a list of sizes ("M6, M8, M10x1.25" or "5, 6.8, 8.5"); one tool is added per size. Sizes that cannot be read are listed before saving.
- **Inserts from the cutter.** An insert cutter has a **New insert…** button beside its insert list, so the insert can be created and linked without changing tab.
- Taps can record cutting or form, and drills a point angle. A library tap's cutting/form choice is used on the Guided form.
- Older taps that carry the thread only in the name or diameter open with thread size and pitch filled in.

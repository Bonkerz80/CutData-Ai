# CutData AI 0.2.10

- **Update box.** A few seconds after it starts, the installed app checks this project's public GitHub releases for a newer version. If there is one, a box shows the new version and its release notes with four choices: **Download and install**, **Open release page**, **Skip this version** and **Later**.
- **Download and install** fetches the installer from the release, confirms its size and published checksum, starts it and closes the app so the files can be replaced. Settings, tool library and history are kept.
- The check is silent when there is nothing new or no internet connection, and it never interrupts a running calculation.
- **About** has a **Check for updates** button and a tick box to turn the start-up check off.
- Only an installer attached to a release of this project is ever downloaded. The check sends nothing about you or your work; it is a plain request for the latest release.

# Install StarCapsule Studio

[简体中文](INSTALL.zh-CN.md) · [Review guide](REVIEW.md)

## Complete Windows x64 package

1. Download the `StarCapsule-Studio-0.4.0-Windows-x64.zip` release asset and extract the **entire** archive.
2. Double-click **Install.cmd**. The included Python/Tk runtime requires no separate Python installation or administrator account.
3. Open **StarCapsule Studio** from the desktop shortcut. You can also run **Launch.cmd** directly in the extracted folder for portable use.

The installer defaults to English. To use Chinese installation messages, open PowerShell in the extracted folder and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -Language zh-CN
```

The application and new reports default to English; select **简体中文** in the desktop header or the HTML's **More** menu. The desktop remembers the local choice; saved HTML and project JSON retain their language independently. Source names and user text remain unchanged.

For an existing installation, close StarCapsule before running the new installer. Keep your jobs, exported reports and custom templates. Updating the application changes future exports; it does not rewrite HTML already delivered. Refresh a report without STAR using a new output filename:

```powershell
starcapsule upgrade old-review.html --output updated-review.html
```

If the command is not on PATH, run it through the installed runtime from the app folder:

```powershell
.\runtime\python.exe -I -m cfd_review upgrade old-review.html --output updated-review.html
```

Use quotes around file paths containing spaces. The command preserves the original by default; choose a new destination filename.

## Source checkout or Python wheel

Python 3.10+ is required; the desktop interface also needs Tkinter. From a source checkout, run `python run.py gui` or use **Open Studio.cmd**. For a wheel, install offline:

```powershell
python -m pip install --no-index starcapsule_studio-0.4.0-py3-none-any.whl
starcapsule-gui
```

## Export and viewing prerequisites

Reading `.sim` requires your own compatible, licensed STAR-CCM+ installation. The app launches its export process in the background; it does not distribute STAR or its license. The current native API profile is 19.02.009; other versions need separate validation.

Viewing needs a local HTML environment with JavaScript and WebGL. The same HTML has desktop and tablet layouts; native gzip decoding is preferred and an embedded offline decoder covers a missing native interface. The selected data and viewer are embedded locally. A file preview that does not run JavaScript/WebGL cannot show the model. Full physical iPad/Safari qualification remains open; see the [tablet guide](MOBILE_REVIEW.md) before choosing a delivery device.

A STAR network-license arrangement can still require its license server during export. See [validation](VALIDATION.md) for tested environments and remaining limits, and the [0.4.0 release notes](RELEASE_NOTES_0.4.0.md) for changes and compatibility.

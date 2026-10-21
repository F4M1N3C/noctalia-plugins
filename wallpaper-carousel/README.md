# Wallpaper Carousel

A full-screen wallpaper carousel for Noctalia: vertical cards for every wallpaper in your
wallpaper folder, a parallax crop that reveals a different part of each image, and a bar
button that opens it.

## Plugin

| Field | Value |
| --- | --- |
| ID | `faminec/wallpaper-carousel` |
| Entries | Bar widget: `button`; panel: `panel` |

## Requirements

The following executables must be installed and available on `PATH`:

- `python3` — runs the thumbnail helper.
- `python-pillow` — the imaging library the thumbnail helper needs.

The plugin reads your Noctalia wallpaper folder (or the folder set in its settings) and
caches one small preview per image in
`~/.local/state/noctalia/plugins/data/faminec/wallpaper-carousel/thumbs/`.

## Usage

Add the `button` bar icon and click it to open the carousel. The panel opens full screen
with the wallpapers laid out as vertical cards; the selected card is highlighted and
slightly larger.

Keyboard:

| Key | Action |
| --- | --- |
| `Left` / `Right` | Move the selection |
| `Home` / `End` | Jump to the first or the last wallpaper |
| `Enter` | Apply the selected wallpaper |
| `Esc` | Close the carousel |
| `r` | Rescan the folder |

The mouse wheel moves through the carousel as well: one notch per wallpaper, in
both directions.

The panel can also be opened directly:

```sh
noctalia msg panel-toggle faminec/wallpaper-carousel:panel
```

## Settings

Configure the plugin in **Settings → Plugins → Wallpaper Carousel**.

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `directory` | `string` | empty | Wallpaper folder. Empty uses Noctalia's configured wallpaper folder. |
| `glyph` | `glyph` | `wallpaper` | Bar icon. |
| `card_scale` | `double` | `1.0` | Initial card size (also adjustable from the panel slider). |
| `gap` | `int` | `18` | Horizontal space between cards, in pixels. |
| `visible` | `int` | `0` | How many cards are shown at once. `0` fills the screen. |
| `minimal` | `bool` | `true` | Hide the header and footer for a minimal look. |
| `parallax` | `double` | `1.0` | How much each thumbnail crop shifts with the card's position. |
| `close_on_apply` | `bool` | `true` | Close the carousel after applying a wallpaper. |
| `apply_all` | `bool` | `true` | Apply to every monitor; when off, only to the focused monitor. |
| `show_filenames` | `bool` | `true` | Show the selected file name in the panel footer. |

## IPC

```sh
noctalia msg panel-toggle faminec/wallpaper-carousel:panel
noctalia msg plugin faminec/wallpaper-carousel:panel all refresh
```

## Notes

- The previews are generated with Pillow at 360×600 in five parallax positions per image
  and cached on disk, so navigating is instant after the first pass. The cards show a
  placeholder while their preview is being generated.
- The previews are written as JPEG: Noctalia's image loader ships the JPEG, PNG and SVG
  handlers only, so a WebP preview would render as an empty placeholder.
- The plugin only reads the wallpaper folder and writes its own cache directory; it
  makes no network requests.
- The panel background is transparent, so the desktop wallpaper shows through the gaps
  between the cards. The card row is centred and the cards fill the width of the
  screen.
- The selection eases towards its target instead of jumping, and the crop of every
  card follows that movement, so the images visibly slide inside their frames.

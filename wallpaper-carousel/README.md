# Wallpaper Carousel

A full-screen wallpaper carousel for Noctalia: a ribbon of vertical cards that overlap
like a 3D strip, with a parallax crop inside every card and a bar button that opens it.

The design follows the "Resizeable wallpaper carousel with parallax effect" by
u/HyperSpazdik and the `motor-dev/wallpaperCarousel` plugin.

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
caches the card images in
`~/.local/state/noctalia/plugins/data/faminec/wallpaper-carousel/thumbs/`.

## Usage

Add the `button` bar icon and click it to open the carousel. The panel opens full screen
with the wallpapers laid out as a ribbon of cards; the card in the centre is the
selected one, larger and fully opaque, and the rest fade out towards the edges.

Keyboard:

| Key | Action |
| --- | --- |
| `Left` / `Right` | Move the selection (hold to repeat) |
| `Home` / `End` | Jump to the first or the last wallpaper |
| `Enter` / `Space` | Apply the selected wallpaper |
| `Esc` | Close the carousel |
| `r` | Rescan the folder |

The mouse wheel moves through the carousel as well: one notch per wallpaper, in both
directions. The wheel is captured by an invisible scroll view that the ribbon lives in,
so the gesture works anywhere over the panel.

Clicking a card selects it and applies it.

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
| `card_width` | `int` | `300` | Width of a card, in pixels. |
| `card_height` | `int` | `420` | Height of a card, in pixels. |
| `skew` | `double` | `0.35` | Skew of the card, from `0` (straight) to `0.8`. |
| `parallax` | `double` | `1.0` | How much the crop inside a card shifts with its position. |
| `selected_scale` | `double` | `1.08` | Scale of the selected card. |
| `base_scale` | `double` | `0.75` | Scale of the cards at the edge of the ribbon. |
| `hover_boost` | `double` | `0.2` | Extra scale while the pointer is over a card. |
| `scrim` | `double` | `0.0` | Darkening applied to the background, from `0` to `0.9`. |
| `close_on_apply` | `bool` | `true` | Close the carousel after applying a wallpaper. |
| `apply_all` | `bool` | `true` | Apply to every monitor; when off, only to the focused monitor. |
| `show_filenames` | `bool` | `true` | Show the selected file name in the footer. |
| `chrome` | `bool` | `false` | Show the footer with the file name and the apply button. |

## IPC

```sh
noctalia msg panel-toggle faminec/wallpaper-carousel:panel
noctalia msg plugin faminec/wallpaper-carousel:panel all refresh
noctalia msg plugin faminec/wallpaper-carousel:panel all next
noctalia msg plugin faminec/wallpaper-carousel:panel all prev
```

## Notes

- The cards are generated with Pillow at the configured size, as RGBA PNGs with the
  wallpaper cropped inside a parallelogram, so the skew of the ribbon is baked into the
  image. The parallax crop is baked in as well, in three positions per wallpaper.
- The previews are written as PNG and not WebP: Noctalia's image loader ships the JPEG,
  PNG and SVG handlers only, so a WebP preview would render as an empty placeholder.
- The plugin only reads the wallpaper folder and writes its own cache directory; it
  makes no network requests.
- The card images are generated in the background; a card shows a placeholder until its
  image is ready.

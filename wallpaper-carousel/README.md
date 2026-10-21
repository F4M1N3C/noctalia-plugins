# Wallpaper Carousel

A full-screen wallpaper carousel for Noctalia: a ribbon of vertical cards leaning to the
right, the selected wallpaper highlighted and slightly larger, and a parallax crop that
reveals a different part of every image as the ribbon slides.

The design follows **"Resizeable wallpaper carousel with parallax effect"** by
[u/HyperSpazdik](https://www.reddit.com/r/hyprland/comments/1vjqvrr/resizeable_wallpaper_carousel_with_parallax_effect/)
and the plugin it grew into, [motor-dev/wallpaperCarousel](https://github.com/motor-dev/wallpaperCarousel)
(which itself credits [ilyamiro](https://github.com/ilyamiro/nixos-configuration) for the original
wallpaper picker).

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
caches one preview per image and per parallax position in
`~/.local/state/noctalia/plugins/data/faminec/wallpaper-carousel/thumbs/`.

## Usage

Add the `button` bar icon and click it to open the carousel. The panel opens full screen
with the wallpapers as a skewed ribbon; the card under the pointer lights up, and clicking a
card applies it.

Keyboard:

| Key | Action |
| --- | --- |
| `Left` / `Right` (or `h` / `l`, `j` / `k`) | Move the selection — holding the key repeats |
| `Home` / `End` | Jump to the first or the last wallpaper |
| `Enter` / `space` | Apply the selected wallpaper |
| `Esc` | Close the carousel |
| `r` | Pick a random wallpaper |

The mouse wheel moves through the carousel as well: one notch per wallpaper, in both
directions.

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
| `card_width` | `int` | `250` | Width of the selected card, in logical pixels. |
| `card_height` | `int` | `350` | Height of the selected card, in logical pixels. |
| `skew` | `double` | `0.35` | How much the cards lean to the right. `0` gives straight cards. |
| `parallax` | `double` | `1.0` | How much each thumbnail crop shifts with the card's position. |
| `selected_scale` | `double` | `1.08` | Size of the selected card relative to the side cards. |
| `base_scale` | `double` | `0.75` | Size of the cards around the selected one. |
| `hover_boost` | `double` | `0.2` | How much the card under the pointer grows and brightens. |
| `scrim` | `double` | `0.0` | Dark veil over the desktop. `0` keeps the background fully transparent. |
| `wheel` | `bool` | `true` | Move the carousel with the mouse wheel. |
| `close_on_apply` | `bool` | `true` | Close the carousel after applying a wallpaper. |
| `apply_all` | `bool` | `true` | Apply to every monitor; when off, only to the focused monitor. |
| `show_filenames` | `bool` | `true` | Show the selected file name in the panel footer. |
| `chrome` | `bool` | `false` | Show the footer with the file name and the apply button. |

### Transparency

The shell draws the panel surface itself, so the wallpaper only shows through if the
panel is translucent. Set **Settings → Shell → Panel → Transparency** to `glass` (or `soft`)
for that; the plugin's own `scrim` setting then adds the dark veil on top.

## IPC

```sh
noctalia msg panel-toggle faminec/wallpaper-carousel:panel
noctalia msg plugin faminec/wallpaper-carousel:panel all refresh
noctalia msg plugin faminec/wallpaper-carousel:panel all next
noctalia msg plugin faminec/wallpaper-carousel:panel all prev
```

## Notes

- Noctalia's declarative UI has no transform props, so the cards' lean is baked into the
  preview: the helper renders the wallpaper upright and masks it with the parallelogram,
  which is what makes the row read as a 3D ribbon. The previews are RGBA PNGs (the JPEG,
  PNG and SVG handlers are the only image formats Noctalia ships).
- The previews are generated in three parallax positions per image and cached on disk, so
  navigating is instant after the first pass. The cards show a placeholder while their
  preview is being generated.
- The panel never reads the keyboard's auto-repeat: a held arrow key delivers one press and
  one release, so the repeat is reproduced from the frame tick instead.
- The mouse wheel is captured by a `ui.scroll` that wraps the ribbon. Its vertical movement
  is cancelled by the scroll's own padding, so the ribbon stays in place while the wheel
  drives the carousel sideways.
- The plugin only reads the wallpaper folder and writes its own cache directory; it makes no
  network requests.

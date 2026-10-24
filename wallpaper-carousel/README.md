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

Add the `button` bar icon and click it to open the carousel. The panel opens on a random
wallpaper as a continuous circular ribbon: there are always cards on both sides, even when the
folder is short or the selected wallpaper is the first or the last one. The card under the
pointer lights up; one click selects a card and a second click on the same card applies it.

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
| `card_width` | `int` | `300` | Width of the selected card, in logical pixels. |
| `card_height` | `int` | `400` | Height of the selected card, in logical pixels. |
| `card_shape` | `select` | `skew` | Card shape: skewed ribbon, rectangle, square, triangle or ellipse. |
| `skew` | `double` | `0.35` | Lean of the skewed ribbon. Only shown when `card_shape` is `skew`. |
| `parallax` | `double` | `1.0` | How much each thumbnail crop shifts with the card's position. |
| `selected_scale` | `double` | `1.08` | Size of the selected card relative to the side cards. |
| `base_scale` | `double` | `0.88` | Size of the cards around the selected one (also sets the ribbon spacing). |
| `hover_boost` | `double` | `0.2` | How much the card under the pointer grows and brightens. |
| `open_random` | `bool` | `true` | Open on a random wallpaper; off opens on the current desktop wallpaper. |
| `scrim` | `double` | `0.0` | Dark veil over the desktop. `0` keeps the background fully transparent. |
| `wheel` | `bool` | `true` | Move the carousel with the mouse wheel. |
| `close_on_apply` | `bool` | `true` | Close the carousel after applying a wallpaper. |
| `apply_all` | `bool` | `true` | Apply to every monitor; when off, only to the focused monitor. |
| `show_filenames` | `bool` | `true` | Show the selected file name. Works on its own; with the footer on, the name is shown there. |
| `chrome` | `bool` | `false` | Show the footer with the file name and the apply button. |

The less common controls (`card_width`, `skew`, `base_scale`, `hover_boost`, `apply_all`)
are marked as advanced in the settings UI and appear behind **Show advanced**. `skew` is
also hidden unless the card shape is the skewed ribbon.

Panel placement, position, layer and the open-near-click behaviour are host-owned settings:
they appear in the same settings page and work with the shell. The panel is dismissed by
clicking outside it, by `Esc`, or by applying a wallpaper (when `close_on_apply` is on).

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

- The ribbon is circular: each slot takes `((center + offset - 1) mod count) + 1`, so the
  first and last wallpapers have neighbours on both sides and the panel never shows an
  empty half.
- Noctalia's declarative UI has no transform props, so the cards' lean (and every other
  shape) is baked into the preview: the helper renders the wallpaper upright and masks it
  with the selected shape, which is what makes the row read as a 3D ribbon. The previews
  are RGBA PNGs (the JPEG, PNG and SVG handlers are the only image formats Noctalia ships).
- Parallax uses three crops per image. The crop switches when a card crosses the centre of
  the ribbon while it slides (not when the animation finishes), so the selected card always
  rests on the centre crop.
- The previews are cached on disk per shape, so navigating is instant after the first pass.
  The cards show a placeholder while their preview is being generated.
- The panel never reads the keyboard's auto-repeat: a held arrow key delivers one press and
  one release, so the repeat is reproduced from the frame tick instead.
- The host only delivers a single `onClick`; double-click is emulated by measuring the gap
  between two clicks with `noctalia.nowMs()` (wall clock, unlike `os.clock()`).
- The mouse wheel is captured by a `ui.scroll` that wraps the ribbon. Its vertical movement
  is cancelled by the scroll's own padding, so the ribbon stays in place while the wheel
  drives the carousel sideways. The plugin API does not expose `scrollbarVisible`, so the
  host draws its thin scrollbar next to the ribbon. The panel size is host-owned; it is
  declared in `plugin.toml` and cannot be resized at runtime.
- The plugin only reads the wallpaper folder and writes its own cache directory; it makes no
  network requests.

## Tests

```sh
lua5.1 bin/test-panel.lua panel.luau   # rendering, circular ribbon, clicks, settings
python3 bin/test-thumbs.py             # shapes, masks, caching, parallax crops
python3 bin/check-callback-budget.py --open
```

## Changelog

### 2.1.0

- The ribbon is circular and opens on a random wallpaper; there are cards on both sides even
  on the first or last wallpaper.
- Cards are larger and sit in adjacent slots, so the ribbon reads as one continuous strip.
- New `card_shape` setting: skewed ribbon, rectangle, square, triangle or ellipse.
- Double click (two clicks within 450 ms) applies the wallpaper; a single click selects.
- `show_filenames` now works without the footer.
- The parallax crop switches while the ribbon slides instead of when the animation ends.
- The panel is dismissed by clicking outside it (`dismiss_on_outside_click`).
- Settings are grouped: less common controls are marked advanced and `skew` only appears for
  the skewed shape.
- Regression tests for the panel and the thumbnail helper.

/* No-grab autocomplete for a plain <input> - replaces the tkinter app's
 * _LiveDropdown (a Toplevel+Listbox popup that never steals OS focus, to
 * avoid breaking the app's click-through/always-on-top model). A DOM
 * popover inside the same window inherently satisfies that constraint,
 * no extra focus handling needed.
 *
 * getValues() is called fresh on every keystroke/focus (mirroring
 * _LiveDropdown's pre_fn - e.g. a cascade filter re-querying based on a
 * sibling box's current value) and may return a Promise. onSelect(value)
 * fires after the user picks a suggestion (mirroring on_select_fn).
 */
class LiveDropdown {
  constructor(input, { getValues, onSelect } = {}) {
    this.input = input;
    this.getValues = getValues || (() => []);
    this.onSelect = onSelect || (() => {});

    this.list = document.createElement("div");
    this.list.className = "dropdown-list";
    const parent = input.parentElement;
    if (getComputedStyle(parent).position === "static") {
      parent.style.position = "relative";
    }
    parent.appendChild(this.list);

    input.addEventListener("input", () => this._refresh());
    input.addEventListener("focus", () => this._refresh());
    input.addEventListener("keydown", (e) => this._onKeydown(e));
    // mousedown (not click) fires before the input's blur, so the value
    // is applied before the list gets hidden by the blur handler below.
    input.addEventListener("blur", () => {
      setTimeout(() => this._hide(), 100);
    });

    this._activeIndex = -1;
  }

  async _refresh() {
    const values = await this.getValues();
    const q = this.input.value.trim().toLowerCase();
    const matches = q
      ? values.filter((v) => v.toLowerCase().includes(q))
      : values;
    this._render(matches);
  }

  _render(matches) {
    this.list.innerHTML = "";
    this._activeIndex = -1;
    if (matches.length === 0) {
      this._hide();
      return;
    }
    for (const v of matches.slice(0, 50)) {
      const item = document.createElement("div");
      item.className = "dropdown-item";
      item.textContent = v;
      item.addEventListener("mousedown", (e) => {
        e.preventDefault();
        this._choose(v);
      });
      this.list.appendChild(item);
    }
    this.list.classList.add("show");
  }

  _choose(value) {
    this.input.value = value;
    this._hide();
    this.onSelect(value);
  }

  _onKeydown(e) {
    const items = Array.from(this.list.children);
    if (!items.length || !this.list.classList.contains("show")) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      this._activeIndex = Math.min(this._activeIndex + 1, items.length - 1);
      this._highlight(items);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      this._activeIndex = Math.max(this._activeIndex - 1, 0);
      this._highlight(items);
    } else if (e.key === "Enter" && this._activeIndex >= 0) {
      e.preventDefault();
      this._choose(items[this._activeIndex].textContent);
    } else if (e.key === "Escape") {
      this._hide();
    }
  }

  _highlight(items) {
    items.forEach((el, i) => el.classList.toggle("active", i === this._activeIndex));
  }

  _hide() {
    this.list.classList.remove("show");
  }
}

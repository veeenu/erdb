from copy import copy
from functools import partial
from math import floor
from typing import Any, Generator, Iterable, NamedTuple, Optional
from js import document, armaments_raw, reinforcements_raw, correction_attack_raw, correction_graph_raw # type: ignore
from pyodide.ffi import JsProxy # type: ignore
from pyodide.ffi.wrappers import add_event_listener # type: ignore
from attack_power import CalculatorData, ArmamentCalculator, Attributes # type: ignore

# define things inherent to py-script runtime
pyscript = pyscript # type: ignore

# instantiating lots of data in JavaScript then porting seems more stable
armaments = armaments_raw.to_py()
reinforcements = reinforcements_raw.to_py()
correction_attack = correction_attack_raw.to_py()
correction_graph = correction_graph_raw.to_py()

calculator_data = CalculatorData(armaments, reinforcements, correction_attack, correction_graph)

def debounce(delay: float):
    def decorator(func):
        def wrapper(*args, **kwargs):
            if hasattr(wrapper, "_handle"):
                wrapper._handle.cancel()

            to_call = partial(func, *args, **kwargs)
            wrapper._handle = pyscript.loop.call_later(delay, to_call)
        return wrapper
    return decorator

class ElementWrapper:
    class _Attributes(NamedTuple):
        parent: "ElementWrapper"

        def __getitem__(self, attrib: str) -> str | None:
            return self.parent._element.getAttribute(attrib)

        def __setitem__(self, attrib: str, value: Any):
            self.parent._element.setAttribute(attrib, value)

        def __contains__(self, item: object) -> bool:
            assert isinstance(item, str)
            return self.parent._element.getAttribute(item) is not None

    class _ClassList(NamedTuple):
        parent: "ElementWrapper"

        def add(self, classname: str):
            self.parent._element.classList.add(classname)

        def remove(self, classname: str):
            self.parent._element.classList.remove(classname)

        def __contains__(self, item: object) -> bool:
            assert isinstance(item, str)
            return item in self.parent._element.classList

    class _ChildList(NamedTuple):
        parent: "ElementWrapper"

        def add(self, element: "ElementWrapper"):
            self.parent._element.appendChild(element._element)

        def remove(self, element: "ElementWrapper"):
            self.parent._element.removeChild(element._element)

    _element: JsProxy
    _attributes: _Attributes
    _class_list: _ClassList
    _child_list: _ChildList

    def __init__(self, value: str | Any) -> None:
        if isinstance(value, str):
            self._element = document.getElementById(value)
        elif isinstance(value, JsProxy):
            self._element = value
        else:
            assert "Invalid `value` type for ElementWrapper"

        self._attributes = self._Attributes(self)
        self._class_list = self._ClassList(self)
        self._child_list = self._ChildList(self)

    @property
    def attributes(self) -> "ElementWrapper._Attributes":
        return self._attributes

    @property
    def class_list(self) -> "ElementWrapper._ClassList":
        return self._class_list

    @property
    def child_list(self) -> "ElementWrapper._ChildList":
        return self._child_list

    @property
    def value(self) -> Any:
        return self._element.value

    @value.setter
    def value(self, value: Any):
        self._element.value = value

    @property
    def inner_text(self) -> str:
        return self._element.innerText

    @inner_text.setter
    def inner_text(self, value: str):
        self._element.innerText = value

    @property
    def inner_html(self) -> str:
        return self._element.innerHTML

    @inner_html.setter
    def inner_html(self, value: str):
        self._element.innerHTML = value

    @property
    def src(self) -> str:
        return self._element.src

    @src.setter
    def src(self, value: str):
        self._element.src = value

    @property
    def is_enabled(self) -> bool:
        return not self._element.disabled

    @is_enabled.setter
    def is_enabled(self, value: bool):
        self._element.disabled = not value

    @property
    def is_visible(self) -> bool:
        return not self._element.hidden

    @is_visible.setter
    def is_visible(self, value: bool):
        self._element.hidden = not value

    def clone(self) -> "ElementWrapper":
        return ElementWrapper(self._element.cloneNode(True, deep=True))

    def click(self):
        self._element.click()

    def add_listener(self, event: str, callback, **kwargs):
        # pyodide wrappers introduce some irrelevant args
        call = lambda *args: callback(element=self, **kwargs)
        add_event_listener(self._element, event, call)

    # TODO: use `Self | None` when 3.11 is available
    def find_id(self, index: str, from_content: bool = False) -> Optional["ElementWrapper"]:
        origin = self._element.content if from_content else self._element
        if element := origin.querySelector(f"#{index}"):
            return ElementWrapper(element)

        return None

    def find_tag(self, tag: str) -> Generator["ElementWrapper", None, None]:
        return (ElementWrapper(e) for e in self._element.getElementsByTagName(tag))

class AttributeMenu:
    _callback = None
    _attribs: list[ElementWrapper] = [
        ElementWrapper("player-attributes-strength"),
        ElementWrapper("player-attributes-dexterity"),
        ElementWrapper("player-attributes-intelligence"),
        ElementWrapper("player-attributes-faith"),
        ElementWrapper("player-attributes-arcane"),
    ]

    def register_callback(self, callback) -> Attributes:
        assert self._callback is None
        self._callback = callback

        for e in self._attribs:
            e.add_listener("input", self._on_change)

        return self._create_attribs()

    def _create_attribs(self):
        return Attributes(*(int(elem.value) for elem in self._attribs))

    def _on_change(self, element: ElementWrapper):
        try:
            value = max(1, min(99, int(element.value)))

        except ValueError:
            return

        element.value = value
        self._callback(self._create_attribs()) # type: ignore (optimization to not assert)

class ArmamentEntry(NamedTuple):
    key: str
    wrapped: ElementWrapper

    # NamedTuple properties cannot start with _, but wanna keep using them because
    # tuples are implemented in C and are faster. This is based on no profiling whatsoever.
    priv_title: ElementWrapper
    priv_icon: ElementWrapper
    priv_affinities: ElementWrapper
    priv_levels: ElementWrapper
    priv_remove: ElementWrapper
    priv_requirement: dict[str, ElementWrapper]
    priv_scaling: dict[str, ElementWrapper]
    priv_attack_power: dict[str, ElementWrapper]
    priv_status_effect: dict[str, ElementWrapper]
    priv_guard: dict[str, ElementWrapper]
    priv_resistance: dict[str, ElementWrapper]

    @staticmethod
    def _normalize(value: int) -> str:
        return "-" if value == 0 else str(value)

    @staticmethod
    def _wrap_list(start_tag: str, values: Iterable[str], end_tag: str) -> str:
        return start_tag + f"{end_tag}{start_tag}".join(values) + end_tag

    def set_title(self, name: str, icon_id: int):
        self.priv_title.inner_text = name
        self.priv_icon.src = f"https://assets.erdb.workers.dev/icons/armaments/{icon_id}/menu"

    def set_affinities(self, affinities: list[str]):
        self.priv_affinities.inner_html = self._wrap_list("<option>", affinities, "</option>")
        self.priv_affinities.is_enabled = len(affinities) > 1

    def set_levels(self, levels: list[str]):
        self.priv_levels.inner_html = self._wrap_list("<option>", levels, "</option>")

    def set_attack_power(self, attack_type: str, value: int):
        self.priv_attack_power[attack_type].inner_text = self._normalize(value)

    def set_guard(self, guard_type: str, value: int):
        self.priv_guard[guard_type].inner_text = self._normalize(value)

    def set_status_effect(self, effect_type: str, value: int):
        self.priv_status_effect[effect_type].inner_text = self._normalize(value)

    def set_resistance(self, resistance_type: str, value: int):
        self.priv_resistance[resistance_type].inner_text = self._normalize(value)

    def set_scaling(self, attribute: str, value: float):
        def grade() -> str:
            if value >= 1.75: return "S"
            if value >= 1.4: return "A"
            if value >= 0.9: return "B"
            if value >= 0.6: return "C"
            if value >= 0.25: return "D"
            if value > 0.0: return "E"
            return "-"

        self.priv_scaling[attribute].inner_text = grade()
        self.priv_scaling[attribute].attributes["uk-tooltip"] = round(value, 2)

    def set_requirement(self, attribute: str, armament_value: int, player_value: int):
        is_met = player_value >= armament_value

        getattr(self.priv_requirement[attribute].class_list, "remove" if is_met else "add")("uk-text-danger")
        self.priv_requirement[attribute].inner_text = self._normalize(armament_value)

    def add_remove_listener(self, callback):
        self.priv_remove.add_listener("click", callback, armentry=self)

    def add_affinities_listener(self, callback):
        self.priv_affinities.add_listener("change", callback, armentry=self)

    def add_levels_listener(self, callback):
        self.priv_levels.add_listener("change", callback, armentry=self)

    @classmethod
    def create(cls, key: str, element: ElementWrapper):
        def get(template_id_part: str):
            if e := element.find_id(f"armament-display-{template_id_part}"):
                return e
            assert False, f"\"{template_id_part}\" invalid"

        return cls(key, element,
            priv_title=get("title"),
            priv_icon=get("icon"),
            priv_affinities=get("affinities"),
            priv_levels=get("levels"),
            priv_remove=get("remove"),
            priv_requirement={
                "strength": get("requirement-strength"),
                "dexterity": get("requirement-dexterity"),
                "intelligence": get("requirement-intelligence"),
                "faith": get("requirement-faith"),
                "arcane": get("requirement-arcane"),
            },
            priv_scaling={
                "strength": get("scaling-strength"),
                "dexterity": get("scaling-dexterity"),
                "intelligence": get("scaling-intelligence"),
                "faith": get("scaling-faith"),
                "arcane": get("scaling-arcane"),
            },
            priv_attack_power={
                "total": get("attack-power-total"),
                "physical": get("attack-power-physical"),
                "magic": get("attack-power-magic"),
                "fire": get("attack-power-fire"),
                "lightning": get("attack-power-lightning"),
                "holy": get("attack-power-holy"),
            },
            priv_status_effect={
                "bleed": get("status-effect-bleed"),
                "frostbite": get("status-effect-frostbite"),
                "poison": get("status-effect-poison"),
                "scarlet_rot": get("status-effect-scarlet_rot"),
                "sleep": get("status-effect-sleep"),
                "madness": get("status-effect-madness"),
            },
            priv_guard={
                "boost": get("guard-boost"),
                "physical": get("guard-physical"),
                "magic": get("guard-magic"),
                "fire": get("guard-fire"),
                "lightning": get("guard-lightning"),
                "holy": get("guard-holy"),
            },
            priv_resistance={
                "bleed": get("resistance-bleed"),
                "frostbite": get("resistance-frostbite"),
                "poison": get("resistance-poison"),
                "scarlet_rot": get("resistance-scarlet_rot"),
                "sleep": get("resistance-sleep"),
                "madness": get("resistance-madness"),
            },
        )

class ArmamentEntryFactory(NamedTuple):
    template = ElementWrapper("armament-display-template").find_id("armament-display-element", from_content=True)

    def create(self, key: str, on_remove) -> ArmamentEntry:
        assert self.template, "Template not found"

        armament = armaments[key]
        et = ArmamentEntry.create(key, self.template.clone())
        et.set_title(armament["name"], armament["icon"])

        if len(armament["affinity"]) > 1:
            sorted_affinities = [k for k, _ in sorted(armament["affinity"].items(), key=lambda x: x[1]["id"])]
            et.set_affinities(sorted_affinities)
        else:
            is_somber = armament["upgrade_material"].startswith("Somber")
            et.set_affinities(["Somber"] if is_somber else ["Standard"])

        levels = [f"+{i}" for i in range(0, len(armament["upgrade_costs"]) + 1)]
        et.set_levels(levels)

        et.add_remove_listener(on_remove)

        return et

class ArmamentContainer:
    _container = ElementWrapper("armament-display-container")
    _attribs: Attributes = None
    _calcs: dict[str, ArmamentCalculator] = {}
    _elems: dict[str, ArmamentEntry] = {}

    def __init__(self, attribute_menu: AttributeMenu) -> None:
        self._attribs = attribute_menu.register_callback(self._on_attributes)

    @staticmethod
    def _update_values(et: ArmamentEntry, calc: ArmamentCalculator, attribs: Attributes):
        armament = armaments[et.key]
        affinity = armament["affinity"][calc.affinity]
        reinforcement = reinforcements[str(affinity["reinforcement_id"])][calc.level]

        ap = calc.attack_power(attribs)

        et.set_attack_power("total", ap.total)
        et.set_guard("boost", floor(affinity["guard"].get("guard_boost", 0.) * reinforcement["guard"]["guard_boost"]))

        for attack_type, value in ap.items():
            et.set_attack_power(attack_type, value.total)
            et.set_guard(attack_type, floor(affinity["guard"].get(attack_type, 0.) * reinforcement["guard"][attack_type]))

        for effect_type, value in calc.status_effects(attribs).items():
            et.set_status_effect(effect_type, value.total)
            et.set_resistance(effect_type, floor(affinity["resistance"].get(effect_type, 0.) * reinforcement["resistance"][effect_type]))

        for attribute in ["strength", "dexterity", "intelligence", "faith", "arcane"]:
            et.set_scaling(attribute, affinity["scaling"].get(attribute, 0.) * reinforcement["scaling"][attribute])
            et.set_requirement(attribute, armament["requirements"].get(attribute, 0), getattr(attribs, attribute))

    def _on_attributes(self, attribs: Attributes):
        self._attribs = attribs

        for et in self._elems.values():
            self._update_values(et, self._calcs[et.key], self._attribs)

    def _on_affinity(self, element: ElementWrapper, armentry: ArmamentEntry):
        self._calcs[armentry.key].set_affinity(element.value, calculator_data)
        self._update_values(armentry, self._calcs[armentry.key], self._attribs)

    def _on_level(self, element: ElementWrapper, armentry: ArmamentEntry):
        level = int(element.value[1:]) # drop initial "+"
        self._calcs[armentry.key].set_level(level, calculator_data)
        self._update_values(armentry, self._calcs[armentry.key], self._attribs)

    def add(self, armentry: ArmamentEntry):
        self._calcs[armentry.key] = ArmamentCalculator(calculator_data, armentry.key, "Standard", 0)
        self._elems[armentry.key] = armentry

        armentry.add_affinities_listener(self._on_affinity)
        armentry.add_levels_listener(self._on_level)

        self._update_values(armentry, self._calcs[armentry.key], self._attribs)
        self._container.child_list.add(armentry.wrapped)

    def remove(self, key: str):
        self._container.child_list.remove(self._elems[key].wrapped)
        del self._calcs[key]
        del self._elems[key]

class ArmamentSelector:
    class _Armament(NamedTuple):
        wrapped: ElementWrapper
        key: str
        category: str
        tags: str
        active_class = "uk-button-primary"

        @staticmethod
        def has_key(element: ElementWrapper) -> bool:
            return "data-armament-key" in element.attributes

        @classmethod
        def create(cls, element: ElementWrapper) -> "ArmamentSelector._Armament":
            key = element.attributes["data-armament-key"]
            category = element.attributes["data-armament-category"]
            assert key and category, "data-armament-key or data-armament-category missing from the element"

            return cls(element, key, category,
                tags=f"{key.lower()} {category.lower()}"
            )

        @property
        def is_selected(self) -> bool:
            return self.active_class in self.wrapped.class_list

        def select(self):
            self.wrapped.class_list.add(self.active_class)

        def deselect(self):
            self.wrapped.class_list.remove(self.active_class)

    _factory: ArmamentEntryFactory
    _container: ArmamentContainer

    _filter_field: ElementWrapper
    _choices: list[_Armament]
    _categories: dict[str, ElementWrapper]
    _category_buttons: list[ElementWrapper]

    _selection: set[str] = set()
    _temporary: set[str] = set()

    _open_button = ElementWrapper("open-armament-selection")
    _save_button = ElementWrapper("save-armament-selection")

    _is_open = False

    def __init__(self, factory: ArmamentEntryFactory, container: ArmamentContainer) -> None:
        category_names = {a["category"] for a in armaments.values()}
        as_key = lambda v: v.lower().replace("'", "").replace(".", "").replace(" ", "-") 

        self._category_buttons = [ElementWrapper(f"selection-category-{as_key(cat)}") for cat in category_names]

        for e in self._category_buttons:
            e.add_listener("click", self.on_category)

        for e in (ElementWrapper(f"selection-armament-{as_key(arm)}") for arm in armaments):
            e.add_listener("click", self.on_armament)

        ElementWrapper("toggle-armament-selection").add_listener("click", self.on_all_armaments)
        ElementWrapper("open-armament-selection").add_listener("click", self.on_open)
        ElementWrapper("save-armament-selection").add_listener("click", self.on_save)
        ElementWrapper("close-armament-selection").add_listener("click", self.on_close)

        self._filter_field = ElementWrapper("filter-armament-selection")
        self._filter_field.add_listener("input", self._on_filter)

        self._factory = factory
        self._container = container

        grid = ElementWrapper("armament-selection-grid")
        self._choices = [self._Armament.create(a) for a in [*grid.find_tag("a")] if self._Armament.has_key(a)]
        self._categories = {cat: ElementWrapper(f"armament-selection-category-{as_key(cat)}") for cat in category_names}

    @debounce(0.25)
    def _on_filter(self, element: ElementWrapper):
        visible_categories = set()
        is_empty = len(element.value) == 0

        for choice in self._choices:
            if element.value.lower() in choice.tags:
                choice.wrapped.is_visible = True
                visible_categories.add(choice.category)
            else:
                choice.wrapped.is_visible = False

        for cat, e in self._categories.items():
            e.is_visible = cat in visible_categories

        for button in self._category_buttons:
            button.is_visible = is_empty

    def _on_remove(self, element: ElementWrapper, armentry: ArmamentEntry):
        self._container.remove(armentry.key)
        self._selection.remove(armentry.key)
        self._update_open_button()

    def _update_open_button(self):
        self._open_button.inner_html = "Select Armaments..." if len(self._selection) == 0 \
            else "<b>1</b> Armament Selected" if len(self._selection) == 1 \
            else f"<b>{len(self._selection)}</b> Armaments Selected"

    def _update_save_button(self):
        self._save_button.inner_html = f"Save (<b>{len(self._temporary)}</b>)"

    def toggle(self):
        self._open_button.click()

    @debounce(0.3) # larger debounce than _on_filter to postpone the save after filter is completed
    def select_and_save(self):
        if not self._is_open or len(self._filter_field.value) == 0:
            return

        [self.on_armament(element=a.wrapped) for a in self._choices if not a.is_selected and a.wrapped.is_visible]
        self.on_save()
        self.toggle()

    def on_open(self, element: ElementWrapper | None = None):
        self._temporary = copy(self._selection)

        # re-select every choice (there may be leftovers from cancelling)
        for arm in self._choices:
            arm.deselect()

            if arm.key in self._temporary:
                arm.select()

        self._update_save_button()
        self._is_open = True

    def on_save(self, element: ElementWrapper | None = None):
        for removed in self._selection.difference(self._temporary):
            self._container.remove(removed)

        for added in self._temporary.difference(self._selection):
            et = self._factory.create(added, self._on_remove)
            self._container.add(et)

        self._selection = copy(self._temporary)
        self.on_close()

    def on_close(self, element: ElementWrapper | None = None):
        self._temporary.clear()
        self._filter_field.value = ""

        self._on_filter(element=self._filter_field)
        self._update_open_button()
        self._is_open = False

    def on_category(self, element: ElementWrapper):
        choices = [
            arm for arm in self._choices
            if arm.category == element.attributes["data-armament-category"]
        ]

        if all(a.is_selected for a in choices):
            [self.on_armament(element=a.wrapped) for a in choices if a.is_selected]

        else:
            [self.on_armament(element=a.wrapped) for a in choices if not a.is_selected]

    def on_armament(self, element: ElementWrapper):
        arm = self._Armament.create(element)

        if arm.is_selected:
            self._temporary.remove(arm.key)
            arm.deselect()

        else:
            self._temporary.add(arm.key)
            arm.select()

        self._update_save_button()

    def on_all_armaments(self, element: ElementWrapper | None = None):
        if all(a.is_selected for a in self._choices if a.wrapped.is_visible):
            [self.on_armament(element=a.wrapped) for a in self._choices if a.is_selected and a.wrapped.is_visible]

        else:
            [self.on_armament(element=a.wrapped) for a in self._choices if not a.is_selected and a.wrapped.is_visible]

factory = ArmamentEntryFactory()
attribute_menu = AttributeMenu()
container = ArmamentContainer(attribute_menu)

selector = ArmamentSelector(factory, container)
selector.on_save()

def on_key_down(keyboard_event):
    if keyboard_event.code == "Slash":
        keyboard_event.preventDefault()
        selector.toggle()
    elif keyboard_event.code == "Enter":
        keyboard_event.preventDefault()
        selector.select_and_save()

add_event_listener(document, "keydown", on_key_down)
from __future__ import annotations

from build_standard_usecase_exports import DIAGRAMS, OUT, make_scene
from render_usecase_sequence_exports import scene_to_png, scene_to_svg


def main() -> None:
    for spec in DIAGRAMS:
        scene = make_scene(spec)
        name = f"hinh_{spec['number'].replace('.', '_')}_usecase_{spec['slug']}"
        (OUT / f"{name}.svg").write_text(scene_to_svg(scene), encoding="utf-8")
        scene_to_png(scene, OUT / f"{name}.png")
    print(f"Rendered {len(DIAGRAMS)} standard UML use-case SVG and PNG pairs in {OUT}")


if __name__ == "__main__":
    main()

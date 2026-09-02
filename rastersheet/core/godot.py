"""Godot SpriteFrames resource text.

One AtlasTexture sub-resource per frame, all pointing at the same sheet.
"""

TEXTURE_ID = "1_tex"


def sprite_frames_tres(image_res_path, layout, animation_name, fps, loop):
    count = len(layout.cells)
    lines = [
        f'[gd_resource type="SpriteFrames" load_steps={count + 2} format=3]',
        "",
        f'[ext_resource type="Texture2D" path="{image_res_path}" id="{TEXTURE_ID}"]',
        "",
    ]

    for index, cell in enumerate(layout.cells):
        lines.extend(
            [
                f'[sub_resource type="AtlasTexture" id="AtlasTexture_{index}"]',
                f'atlas = ExtResource("{TEXTURE_ID}")',
                f"region = Rect2({cell.x}, {cell.y}, {cell.width}, {cell.height})",
                "",
            ]
        )

    frames = ", ".join(
        f'{{"duration": 1.0, "texture": SubResource("AtlasTexture_{index}")}}'
        for index in range(count)
    )
    lines.extend(
        [
            "[resource]",
            "animations = [{",
            f'"frames": [{frames}],',
            f'"loop": {"true" if loop else "false"},',
            f'"name": &"{animation_name}",',
            f'"speed": {fps}',
            "}]",
            "",
        ]
    )
    return "\n".join(lines)

# Grounding：坐标、单位与 cookbook 的坑

依据 Qwen3-VL cookbook：

- 2D: <https://github.com/QwenLM/Qwen3-VL/blob/main/cookbooks/2d_grounding.ipynb>
- 3D: <https://github.com/QwenLM/Qwen3-VL/blob/main/cookbooks/3d_grounding.ipynb>

## 1. 2D grounding

### 坐标单位

| 模型 | 坐标系 | 换算 |
|---|---|---|
| Qwen3-VL | **0–1000 相对坐标**（相对发送给模型的那张图） | `px = v / 1000 * 原图边长` |
| Qwen2.5-VL | resize 后图上的**绝对像素** | `px = v * 原图边长 / 模型实际输入边长` |

cookbook 原话：

> Qwen3-VL's default coordinate system has been changed from the absolute
> coordinates used in Qwen2.5-VL to relative coordinates ranging from 0 to 1000.
> (You don't need to calculate the resized_w)

所以用 Qwen3-VL 时**不要**去算 smart_resize 后的宽高；只有 Qwen2.5 才需要，而且
必须知道服务端实际 resize 的尺寸，猜不出来就会整体偏移。`vision.py` 对 Qwen2.5
强制要求 `--sent-size WxH`，否则直接报错。

### 图片 resize 的三个注意点

1. **等比缩放不影响相对坐标**：把长边缩到 2048（`VISION_MAX_EDGE`）后，0–1000 的
   参考系不变，映射仍用原图宽高即可。
2. **裁切会影响**：裁切后 0–1000 是相对裁剪图的，必须加偏移
   （`x_orig = x_crop + offset_x`）。本工具默认不裁切；`tile` 只用于文本，不用于 grounding。
3. **EXIF 方向**：手机照片常带 Orientation。必须先 `exif_transpose` 再读宽高，
   否则框会整体旋转 90°。`vision.py` 已处理。

### 后处理

- 模型可能输出 `x1 > x2` 或 `y1 > y2` → 交换
- 越界 → clamp 到 `[0, w]` / `[0, h]`
- 框退化（宽或高为 0）→ 丢弃
- 坐标 > 1000 → 大概率模型返回了绝对坐标，用 `--coord abs` + `--sent-size` 显式声明

### Prompt 模板

多目标（cookbook）：

```
Locate every instance that belongs to the following categories: "<cats>".
Report bbox coordinates in JSON format like this:
{"bbox_2d": [x1, y1, x2, y2], "label": "..."}
```

点定位：

```
Locate every <target> in the image with points. Report point coordinates in
JSON format like this: {"point_2d": [x, y], "label": "..."}
```

单目标也可以用自然语言（"Locate the top right brown cake, output its bbox
coordinates using JSON format."），效果取决于模型。同一请求里**不要混用框和点**。

## 2. 3D grounding

### 数据格式

```
[x_center, y_center, z_center, x_size, y_size, z_size, roll, pitch, yaw]
```

- 中心与尺寸：**米**
- 角度：文档写 radians，但 cookbook 可视化代码先 `*180` 再 `deg2rad`，等价于
  **π 弧度**（0.5 = 90°）。实测 `qwen3.7-plus` 返回 `0.5`，与 π 单位一致
- 坐标系：相机坐标系，X 右、Y 下、Z 前；投影 `x = fx*X/Z + cx`
- 需要相机内参 `fx, fy, cx, cy`（原图像素）。没有时用 `--fov 60` 生成近似值

### 两处 cookbook 不一致（本工具都支持切换）

| 项 | 文档 | cookbook 代码 | 本工具默认 | 覆盖参数 |
|---|---|---|---|---|
| 角度单位 | radians | π 弧度（`*180` 后 `deg2rad`） | `pi` | `--angle-unit rad\|deg` |
| 旋转顺序 | roll, pitch, yaw | 解包成 pitch, yaw, roll 后按 pitch→yaw→roll 应用 | `code` | `--rot-order spec` |

如果画出来的 3D 框朝向明显不对，先试 `--rot-order spec`；如果框大小/朝向都合理但
角度差一个 π 倍，改 `--angle-unit rad`。

### 内参缺失

`--fov 60` 的默认内参：

```
fx = w / (2 * tan(60°/2))
fy = h / (2 * tan(60°/2))
cx = w/2, cy = h/2
```

JSON 里会写 `"source": "assumed-fov60"`。此时 3D 框**只用于示意**，不要据此给出
精确距离、速度或碰撞判断。有真实内参（车载相机标定、手机 EXIF 焦距）时用
`--cam fx,fy,cx,cy`。

### 质量与限制

- 单图估计，依赖模型对场景尺度的先验；俯视图/鱼眼/全景效果差
- 不输出点云、不做多视角融合、不做跟踪
- 输出米制数值是模型估计，不是测量值

## 3. 验收清单

- [ ] `ground2d` 输出同时含 0–1000 与原图像素两套坐标
- [ ] 1920×1080 图上的框叠加后与目标吻合（无整体缩放/偏移）
- [ ] EXIF 旋转照片的框位置正确
- [ ] `ground3d` 的投影与 cookbook `convert_3dbbox` 误差 ≤ 1px
      （`--angle-unit pi --rot-order code`）
- [ ] 非 Qwen3-VL 模型调用 grounding 时给出明确报错，而不是返回空
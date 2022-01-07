import os
import glob
import requests
import threading
import tkinter as tk
from tkinter import Label, filedialog, Text
import cv2
import numpy as np
import torch
from utils import util_calculate_psnr_ssim as util
from models_config import MODLES
from models.network_swinir import SwinIR as net
from PIL import Image, ImageTk, ImageDraw
import time


class Main:

    paths = []
    paths_var = None
    model_item = None
    panel_a = None
    panel_b = None

    tile_power = 50

    def __init__(self) -> None:
        self.init_ui()

    def init_ui(self) -> None:
        window = tk.Tk()
        window.title("SwinIR")

        frame = tk.Frame(window, padx=20, pady=20)
        frame.pack()

        tk.Button(frame, text="select files", command=self.get_paths).pack()

        self.paths_var = tk.StringVar("")
        tk.Label(frame, textvariable=self.paths_var).pack()

        image_container = tk.Frame(frame)

        self.panel_a = ImageDisplay(
            image_container,
            width=500,
            height=500,
            process_preview=self.run_review,
            tile_power=10,
        )
        self.panel_a.pack(side=tk.LEFT)
        self.panel_b = tk.Label(image_container)
        self.panel_b.pack(side=tk.RIGHT)

        image_container.pack()

        selected_model = tk.StringVar(frame)
        selected_model.set(list(MODLES.keys())[0])
        tk.OptionMenu(
            frame, selected_model, *MODLES.keys(), command=self.set_model
        ).pack()
        self.set_model(selected_model.get())

        tk.Button(frame, text="run", command=self.run).pack()

        window.mainloop()

    def get_paths(self):
        self.paths = filedialog.askopenfilenames(
            filetypes=[("Images", "*.jpg *.png *.tif *.tiff"), ("All", "*.*")]
        )
        # self.paths_var.set("\n".join(str(x) for x in self.paths))
        if len(self.paths) > 0:
            self.update_image(self.paths[0])

    def update_image(self, path) -> None:
        if self.model_item:
            border, window_size = self.setup(self.model_item)

            self.panel_a.set_image(path, window_size)

    def set_model(self, model_key):
        if model_key in MODLES:
            self.model_item = MODLES[model_key]

    def run(self):
        self.fetch_model(self.run_model)

    def fetch_model(self, callback, args=[]):
        if self.model_item:
            model_item = self.model_item
            model_path = model_item["path"]

            if os.path.exists(model_path):
                print(f"loading model from {model_path}")
                threading.Thread(target=callback, args=args).start()
            else:

                def download_model():
                    os.makedirs(os.path.dirname(model_path), exist_ok=True)
                    url = f"https://github.com/JingyunLiang/SwinIR/releases/download/v0.0/{os.path.basename(model_path)}"
                    r = requests.get(url, allow_redirects=True)
                    print(f"downloading model {model_path}")
                    open(model_path, "wb").write(r.content)
                    threading.Thread(target=callback, args=args).start()

                threading.Thread(target=download_model).start()

    def define_model(self, model_item):
        task = model_item["task"]

        # 001 classical image sr
        if task == "classical_sr":
            upscale = model_item["scale"]
            training_patch_size = model_item["training_patch_size"]
            model = net(
                upscale=upscale,
                in_chans=3,
                img_size=training_patch_size,
                window_size=8,
                img_range=1.0,
                depths=[6, 6, 6, 6, 6, 6],
                embed_dim=180,
                num_heads=[6, 6, 6, 6, 6, 6],
                mlp_ratio=2,
                upsampler="pixelshuffle",
                resi_connection="1conv",
            )
            param_key_g = "params"

        # 002 lightweight image sr
        # use 'pixelshuffledirect' to save parameters
        elif task == "lightweight_sr":
            upscale = model_item["scale"]
            model = net(
                upscale=upscale,
                in_chans=3,
                img_size=64,
                window_size=8,
                img_range=1.0,
                depths=[6, 6, 6, 6],
                embed_dim=60,
                num_heads=[6, 6, 6, 6],
                mlp_ratio=2,
                upsampler="pixelshuffledirect",
                resi_connection="1conv",
            )
            param_key_g = "params"

        # 003 real-world image sr
        elif task == "real_sr":
            model_size = model_item["model_size"]
            if model_size == "m":
                # use 'nearest+conv' to avoid block artifacts
                model = net(
                    upscale=4,
                    in_chans=3,
                    img_size=64,
                    window_size=8,
                    img_range=1.0,
                    depths=[6, 6, 6, 6, 6, 6],
                    embed_dim=180,
                    num_heads=[6, 6, 6, 6, 6, 6],
                    mlp_ratio=2,
                    upsampler="nearest+conv",
                    resi_connection="1conv",
                )
            else:
                # larger model size; use '3conv' to save parameters and memory; use ema for GAN training
                model = net(
                    upscale=4,
                    in_chans=3,
                    img_size=64,
                    window_size=8,
                    img_range=1.0,
                    depths=[6, 6, 6, 6, 6, 6, 6, 6, 6],
                    embed_dim=240,
                    num_heads=[8, 8, 8, 8, 8, 8, 8, 8, 8],
                    mlp_ratio=2,
                    upsampler="nearest+conv",
                    resi_connection="3conv",
                )
            param_key_g = "params_ema"

        # 004 grayscale image denoising
        elif task == "gray_dn":
            model = net(
                upscale=1,
                in_chans=1,
                img_size=128,
                window_size=8,
                img_range=1.0,
                depths=[6, 6, 6, 6, 6, 6],
                embed_dim=180,
                num_heads=[6, 6, 6, 6, 6, 6],
                mlp_ratio=2,
                upsampler="",
                resi_connection="1conv",
            )
            param_key_g = "params"

        # 005 color image denoising
        elif task == "color_dn":
            model = net(
                upscale=1,
                in_chans=3,
                img_size=128,
                window_size=8,
                img_range=1.0,
                depths=[6, 6, 6, 6, 6, 6],
                embed_dim=180,
                num_heads=[6, 6, 6, 6, 6, 6],
                mlp_ratio=2,
                upsampler="",
                resi_connection="1conv",
            )
            param_key_g = "params"

        # 006 JPEG compression artifact reduction
        # use window_size=7 because JPEG encoding uses 8x8; use img_range=255 because it's sligtly better than 1
        elif task == "jpeg_car":
            model = net(
                upscale=1,
                in_chans=1,
                img_size=126,
                window_size=7,
                img_range=255.0,
                depths=[6, 6, 6, 6, 6, 6],
                embed_dim=180,
                num_heads=[6, 6, 6, 6, 6, 6],
                mlp_ratio=2,
                upsampler="",
                resi_connection="1conv",
            )
            param_key_g = "params"

        pretrained_model = torch.load(model_item["path"])
        model.load_state_dict(
            pretrained_model[param_key_g]
            if param_key_g in pretrained_model.keys()
            else pretrained_model,
            strict=True,
        )

        return model

    def setup(self, model_item):
        # 001 classical image sr/ 002 lightweight image sr
        if model_item["task"] in ["classical_sr", "lightweight_sr"]:
            border = model_item["scale"]
            window_size = 8

        # 003 real-world image sr
        elif model_item["task"] in ["real_sr"]:
            border = 0
            window_size = 8

        # 004 grayscale image denoising/ 005 color image denoising
        elif model_item["task"] in ["gray_dn", "color_dn"]:
            border = 0
            window_size = 8

        # 006 JPEG compression artifact reduction
        elif model_item["task"] in ["jpeg_car"]:
            border = 0
            window_size = 7

        return border, window_size

    def process(self, image, model, model_item, window_size):

        tile_size = window_size * self.tile_power
        tile_overlap = 32

        if tile_size is None:
            # test the image as a whole
            output = model(image)
        else:
            # test the image tile by tile
            b, c, h, w = image.size()
            tile = min(tile_size, h, w)
            assert (
                tile % window_size == 0
            ), "tile size should be a multiple of window_size"
            sf = model_item["scale"]

            stride = tile - tile_overlap
            h_idx_list = list(range(0, h - tile, stride)) + [h - tile]
            w_idx_list = list(range(0, w - tile, stride)) + [w - tile]
            E = torch.zeros(b, c, h * sf, w * sf).type_as(image)
            W = torch.zeros_like(E)

            for h_idx in h_idx_list:
                for w_idx in w_idx_list:
                    in_patch = image[..., h_idx : h_idx + tile, w_idx : w_idx + tile]
                    out_patch = model(in_patch)
                    out_patch_mask = torch.ones_like(out_patch)

                    E[
                        ...,
                        h_idx * sf : (h_idx + tile) * sf,
                        w_idx * sf : (w_idx + tile) * sf,
                    ].add_(out_patch)
                    W[
                        ...,
                        h_idx * sf : (h_idx + tile) * sf,
                        w_idx * sf : (w_idx + tile) * sf,
                    ].add_(out_patch_mask)
            output = E.div_(W)

        return output

    def run_review(self, path, x, y, w, h):
        self.fetch_model(self.run_model_preview, [path, x, y, w, h])

    def run_model_preview(self, path, x, y, w, h):
        model_item = self.model_item
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = self.define_model(model_item)
        model.eval()
        model = model.to(device)

        border, window_size = self.setup(model_item)

        x, y, w, h = int(x), int(y), int(w), int(h)
        image = self.get_image(model_item["task"], path)
        image = image[y : y + h, x : x + w]  # crop
        image = np.transpose(
            image if image.shape[2] == 1 else image[:, :, [2, 1, 0]], (2, 0, 1)
        )  # HCW-BGR to CHW-RGB
        image = (
            torch.from_numpy(image).float().unsqueeze(0).to(device)
        )  # CHW-RGB to NCHW-RGB

        with torch.no_grad():
            # pad input image to be a multiple of window_size
            _, _, h_old, w_old = image.size()
            h_pad = (h_old // window_size + 1) * window_size - h_old
            w_pad = (w_old // window_size + 1) * window_size - w_old
            image = torch.cat([image, torch.flip(image, [2])], 2)[
                :, :, : h_old + h_pad, :
            ]
            image = torch.cat([image, torch.flip(image, [3])], 3)[
                :, :, :, : w_old + w_pad
            ]
            output = self.process(image, model, model_item, window_size)
            output = output[
                ..., : h_old * model_item["scale"], : w_old * model_item["scale"]
            ]

        output = output.data.squeeze().float().cpu().clamp_(0, 1).numpy()
        if output.ndim == 3:
            # CHW-RGB to HCW-BGR
            output = np.transpose(output[[2, 1, 0], :, :], (1, 2, 0))

        b, g, r = cv2.split(output * 255.0)
        img = cv2.merge((r, g, b)).astype(np.uint8)
        img = Image.fromarray(img)
        img_tk = ImageTk.PhotoImage(image=img)
        self.panel_b.configure(image=img_tk)
        self.panel_b.img = img_tk

    def run_model(self):
        model_item = self.model_item

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = self.define_model(model_item)
        model.eval()
        model = model.to(device)

        border, window_size = self.setup(model_item)

        for path in self.paths:
            (img_name, img_ext) = os.path.splitext(os.path.basename(path))

            print(img_name)

            image = self.get_image(model_item["task"], path)

            image = np.transpose(
                image if image.shape[2] == 1 else image[:, :, [2, 1, 0]], (2, 0, 1)
            )  # HCW-BGR to CHW-RGB
            image = (
                torch.from_numpy(image).float().unsqueeze(0).to(device)
            )  # CHW-RGB to NCHW-RGB

            # inference
            with torch.no_grad():
                # pad input image to be a multiple of window_size
                _, _, h_old, w_old = image.size()
                h_pad = (h_old // window_size + 1) * window_size - h_old
                w_pad = (w_old // window_size + 1) * window_size - w_old
                image = torch.cat([image, torch.flip(image, [2])], 2)[
                    :, :, : h_old + h_pad, :
                ]
                image = torch.cat([image, torch.flip(image, [3])], 3)[
                    :, :, :, : w_old + w_pad
                ]
                output = self.process(image, model, model_item, window_size)
                output = output[
                    ..., : h_old * model_item["scale"], : w_old * model_item["scale"]
                ]

            # save image
            output = output.data.squeeze().float().cpu().clamp_(0, 1).numpy()
            if output.ndim == 3:
                # CHW-RGB to HCW-BGR
                output = np.transpose(output[[2, 1, 0], :, :], (1, 2, 0))
            # float32 to uint8
            output = (output * 65535.0).round().astype(np.uint16)
            cv2.imwrite(f"output/{img_name}_SwinIR.tif", output)
            # output = (output * 255.0).round().astype(np.uint8)
            # cv2.imwrite(f'output/{img_name}_SwinIR.png', output)
            print("done", img_name)

    def get_image(self, task, path):

        if task in ["classical_sr", "lightweight_sr", "real_sr", "color_dn"]:
            img_lq = cv2.imread(path, cv2.IMREAD_COLOR).astype(np.float32) / 255.0

        elif task in ["gray_dn"]:
            img_lq = cv2.imread(path, cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255.0
            img_lq = np.expand_dims(img_lq, axis=2)

        # 006 JPEG compression artifact reduction (load gt image and generate lq image on-the-fly)
        elif task in ["jpeg_car"]:
            img_lq = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if img_lq.ndim != 2:
                img_lq = util.bgr2ycbcr(img_lq, y_only=True)
            img_lq = np.expand_dims(img_lq, axis=2).astype(np.float32) / 255.0

        return img_lq


class ImageDisplay:
    label = None
    img = None
    img_tk = None
    width = 0
    height = 0

    path = ""

    og_width = 0
    og_height = 0

    window_size = 0

    tile_power = 0

    process_preview = None

    x = 0
    y = 0

    def __init__(
        self, root, width=100, height=100, tile_power=50, process_preview=None
    ) -> None:
        self.width = width
        self.height = height
        self.tile_power = tile_power
        self.process_preview = process_preview
        label = tk.Label(root, image=None)
        label.pack()
        label.bind("<Motion>", self.motion)
        label.bind("<Button-1>", self.click)
        self.label = label

    def click(self, event):
        if self.img:
            x, y = event.x, event.y
            scale = self.og_width / self.img.width
            size = self.window_size * self.tile_power / scale
            img = self.img.copy()
            draw = ImageDraw.Draw(img)
            draw.rectangle((x, y, x + size, y + size))

            image_tk = ImageTk.PhotoImage(img)
            self.label.configure(image=image_tk)
            self.img_tk = image_tk

            self.process_preview(
                self.path, x * scale, y * scale, size * scale, size * scale
            )

    def motion(self, event):
        x, y = event.x, event.y
        self.x = x
        self.y = y
        # print('{}, {}'.format(x, y))

    def set_image(self, path, window_size):
        self.window_size = window_size
        print(window_size)

        # img = fetch_methods(task, path)
        # b, g, r = cv2.split(img * 255.0)
        # img = cv2.merge((r, g, b)).astype(np.uint8)
        # img = Image.fromarray(img)

        self.path = path

        img = Image.open(path)

        self.og_width = img.width
        self.og_height = img.height

        img.thumbnail((self.width, self.height), Image.BICUBIC)
        img_tk = ImageTk.PhotoImage(image=img)
        self.label.configure(image=img_tk)
        self.img = img
        self.img_tk = img_tk

    def pack(self, side=tk.TOP):
        self.label.pack(side=side)


Main()

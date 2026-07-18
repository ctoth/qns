"""Measure repeating structure in an SSI-263 die-image crop."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import numpy as np


def image_size(image_path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["magick", "identify", "-format", "%w %h", str(image_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    width, height = (int(value) for value in result.stdout.split())
    return width, height


def load_grayscale(image_path: Path) -> np.ndarray:
    width, height = image_size(image_path)
    result = subprocess.run(
        ["magick", str(image_path), "-colorspace", "Gray", "-depth", "8", "gray:-"],
        check=True,
        capture_output=True,
    )
    pixels = np.frombuffer(result.stdout, dtype=np.uint8)
    expected_size = width * height
    if pixels.size != expected_size:
        raise ValueError(f"expected {expected_size} pixels, received {pixels.size}")
    return pixels.reshape((height, width))


def parse_crop(value: str) -> tuple[int, int, int, int]:
    try:
        x, y, width, height = (int(part) for part in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("crop must be x,y,width,height") from error
    if min(x, y, width, height) < 0 or width == 0 or height == 0:
        raise argparse.ArgumentTypeError("crop coordinates must be non-negative and non-empty")
    return x, y, width, height


def parse_range(value: str) -> tuple[float, float]:
    try:
        lower, upper = (float(part) for part in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("range must be minimum,maximum") from error
    if lower <= 0 or upper <= lower:
        raise argparse.ArgumentTypeError("range must be positive and increasing")
    return lower, upper


def edge_profile(image: np.ndarray, axis: int) -> np.ndarray:
    differences = np.abs(np.diff(image.astype(np.float64), axis=axis))
    projection_axis = 0 if axis == 1 else 1
    return differences.mean(axis=projection_axis)


def normalized_autocorrelation(profile: np.ndarray, maximum_lag: int) -> np.ndarray:
    centered = profile - profile.mean()
    correlations = np.full(maximum_lag + 1, np.nan)
    for lag in range(1, maximum_lag + 1):
        left = centered[:-lag]
        right = centered[lag:]
        denominator = np.linalg.norm(left) * np.linalg.norm(right)
        if denominator:
            correlations[lag] = float(np.dot(left, right) / denominator)
    return correlations


def local_maxima(correlations: np.ndarray, minimum_lag: int) -> list[tuple[int, float]]:
    maxima = []
    for lag in range(max(2, minimum_lag), len(correlations) - 1):
        score = correlations[lag]
        if score > correlations[lag - 1] and score >= correlations[lag + 1]:
            maxima.append((lag, score))
    return sorted(maxima, key=lambda item: item[1], reverse=True)


def phase_scores(profile: np.ndarray, pitch: int) -> list[tuple[int, float]]:
    scores = [(phase, float(profile[phase::pitch].mean())) for phase in range(pitch)]
    return sorted(scores, key=lambda item: item[1], reverse=True)


def strongest_positions(profile: np.ndarray, count: int) -> list[tuple[int, float]]:
    maxima = []
    for position in range(1, len(profile) - 1):
        value = profile[position]
        if value > profile[position - 1] and value >= profile[position + 1]:
            maxima.append((position, float(value)))
    return sorted(maxima, key=lambda item: item[1], reverse=True)[:count]


def fit_lattice(
    profile: np.ndarray, pitch_range: tuple[float, float]
) -> tuple[float, float, float]:
    coordinates = np.arange(len(profile), dtype=np.float64)
    best = (0.0, 0.0, float("-inf"))
    for pitch in np.linspace(*pitch_range, 201):
        for origin in np.linspace(0.0, pitch, 161, endpoint=False):
            positions = np.arange(origin, len(profile), pitch)
            score = float(np.interp(positions, coordinates, profile).mean())
            if score > best[2]:
                best = (float(pitch), float(origin), score)
    return best


def write_overlay(
    output_path: Path,
    image: np.ndarray,
    x_lattice: tuple[float, float, float] | None,
    y_lattice: tuple[float, float, float] | None,
    y_subdivisions: int,
) -> None:
    rgb = np.repeat(image[:, :, np.newaxis], 3, axis=2)
    if x_lattice:
        pitch, origin, _ = x_lattice
        for position in np.arange(origin, image.shape[1], pitch):
            x = round(position)
            rgb[:, max(0, x - 1) : min(image.shape[1], x + 2)] = (255, 32, 32)
    if y_lattice:
        pitch, origin, _ = y_lattice
        for position in np.arange(origin, image.shape[0], pitch):
            y = round(position)
            rgb[max(0, y - 1) : min(image.shape[0], y + 2), :] = (32, 255, 32)
        if y_subdivisions > 1:
            sub_pitch = pitch / y_subdivisions
            for position in np.arange(origin + sub_pitch, image.shape[0], sub_pitch):
                distance_from_boundary = (position - origin) % pitch
                if np.isclose(distance_from_boundary, 0.0, atol=0.2):
                    continue
                y = round(position)
                rgb[y : min(image.shape[0], y + 1), :] = (32, 192, 255)
    subprocess.run(
        [
            "magick",
            "-size",
            f"{image.shape[1]}x{image.shape[0]}",
            "-depth",
            "8",
            "rgb:-",
            str(output_path),
        ],
        check=True,
        input=rgb.tobytes(),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--crop", type=parse_crop)
    parser.add_argument("--minimum-lag", type=int, default=4)
    parser.add_argument("--maximum-x-lag", type=int, default=100)
    parser.add_argument("--maximum-y-lag", type=int, default=200)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--x-pitch", type=int)
    parser.add_argument("--y-pitch", type=int)
    parser.add_argument("--fit-x", type=parse_range)
    parser.add_argument("--fit-y", type=parse_range)
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--y-subdivisions", type=int, default=1)
    args = parser.parse_args()

    if shutil.which("magick") is None:
        raise SystemExit("ImageMagick 'magick' executable is required")

    image = load_grayscale(args.image)
    if args.crop:
        x, y, width, height = args.crop
        if x + width > image.shape[1] or y + height > image.shape[0]:
            size = f"{image.shape[1]}x{image.shape[0]}"
            raise SystemExit(f"crop {args.crop} exceeds image size {size}")
        image = image[y : y + height, x : x + width]

    print(f"analyzed={image.shape[1]}x{image.shape[0]}")
    fitted_lattices: dict[str, tuple[float, float, float]] = {}
    for name, axis, maximum_lag in (
        ("x", 1, args.maximum_x_lag),
        ("y", 0, args.maximum_y_lag),
    ):
        profile = edge_profile(image, axis)
        correlations = normalized_autocorrelation(profile, maximum_lag)
        candidates = local_maxima(correlations, args.minimum_lag)[: args.count]
        formatted = " ".join(f"{lag}:{score:.4f}" for lag, score in candidates)
        print(f"{name}_lag:correlation {formatted}")
        pitch = args.x_pitch if name == "x" else args.y_pitch
        if pitch:
            phases = phase_scores(profile, pitch)[: min(args.count, pitch)]
            formatted_phases = " ".join(f"{phase}:{score:.4f}" for phase, score in phases)
            print(f"{name}_phase:mean_edge {formatted_phases}")
        positions = strongest_positions(profile, args.count)
        formatted_positions = " ".join(
            f"{position}:{score:.4f}" for position, score in positions
        )
        print(f"{name}_position:edge {formatted_positions}")
        fit_range = args.fit_x if name == "x" else args.fit_y
        if fit_range:
            fitted = fit_lattice(profile, fit_range)
            fitted_lattices[name] = fitted
            print(
                f"{name}_lattice pitch={fitted[0]:.4f} origin={fitted[1]:.4f} "
                f"mean_edge={fitted[2]:.4f}"
            )

    if args.overlay:
        if args.y_subdivisions < 1:
            raise SystemExit("--y-subdivisions must be at least 1")
        write_overlay(
            args.overlay,
            image,
            fitted_lattices.get("x"),
            fitted_lattices.get("y"),
            args.y_subdivisions,
        )
        print(f"overlay={args.overlay}")


if __name__ == "__main__":
    main()

"""Launch an editable example figure with ``python -m deamat``."""

import numpy as np
from matplotlib.figure import Figure

from .mpl_view import MPLView


def main() -> None:
    figure = Figure(figsize=(10, 6), dpi=100, layout="constrained")
    signal, residual = figure.subplots(2, 1, sharex=True, height_ratios=(3, 1))
    x = np.linspace(0, 12, 240)
    expected = np.exp(-x / 7) * np.sin(2 * x)
    measured = expected + 0.08 * np.cos(13 * x)
    signal.plot(x, expected, color="#3878b8", linewidth=2, label="Model")
    signal.scatter(x[::5], measured[::5], color="#d68137", s=22, label="Measurements")
    signal.set(title="Damped signal", ylabel="Amplitude")
    signal.legend()
    signal.grid(alpha=0.2)
    residual.plot(x, measured - expected, color="#568a68", linewidth=1.2)
    residual.axhline(0, color="0.5", linewidth=0.8)
    residual.set(xlabel="Time [s]", ylabel="Residual")
    residual.grid(alpha=0.2)
    MPLView(figure).run()


if __name__ == "__main__":
    main()
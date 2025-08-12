"""
Entry point for the `deamat-demo` console script defined in pyproject.toml.

Running ``python -m deamat`` or invoking the `deamat-demo` script will
display a brief message explaining how to run the included examples.
"""

def main() -> None:
    print(
        "This is a placeholder entry point for deamat.\n"
        "Run the example scripts in the examples/ directory to see the GUI in action."
    )


if __name__ == "__main__":
    main()
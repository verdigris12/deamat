import sys
import pickle
import matplotlib.pyplot as plt

def load_figure(filename):
    with open(filename, 'rb') as file:
        fig = pickle.load(file)
    return fig

def main():
    if len(sys.argv) != 2:
        print("Usage: python mpl_view.py <path_to_pickled_figure>")
        sys.exit(1)

    filename = sys.argv[1]
    fig = load_figure(filename)
    plt.show()

if __name__ == "__main__":
    main()

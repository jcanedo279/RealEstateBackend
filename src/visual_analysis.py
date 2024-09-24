import pandas as pd
import numpy as np
# Distribution graph imports
from scipy.stats import gaussian_kde
from scipy.stats import skew, kurtosis
# Clusting graph imports
from sklearn.manifold import TSNE
from umap import UMAP
from sklearn.cluster import KMeans, DBSCAN
from hdbscan import HDBSCAN
from scipy.cluster.hierarchy import linkage
from sklearn.metrics import silhouette_score, calinski_harabasz_score, davies_bouldin_score

from app_util import BACKEND_PROPERTIES_DF


aggregate_by = 'zip_code'
aggregate_index = 33076

# Separate numeric and categorical columns
numeric_cols = BACKEND_PROPERTIES_DF.select_dtypes(include=['number']).columns.tolist()
categorical_cols = BACKEND_PROPERTIES_DF.select_dtypes(include=['object']).columns.tolist()

# Remove the aggregate_by column from the list of columns to be aggregated
if aggregate_by in numeric_cols:
    numeric_cols.remove(aggregate_by)
if aggregate_by in categorical_cols:
    categorical_cols.remove(aggregate_by)

# Aggregation dictionary for numeric columns
numeric_agg_dict = {col: ['mean', 'sum', 'max', 'min'] for col in numeric_cols}

# Aggregation dictionary for categorical columns (using count as an example)
categorical_agg_dict = {col: ['count'] for col in categorical_cols}


#####################
# DISTRIBUTION DATA #
#####################

def calculate_statistics(data):
    mean_val = data.mean()
    std_dev = data.std()
    median_val = data.median()
    iqr1 = np.percentile(data, 25)
    iqr3 = np.percentile(data, 75)
    skewness = skew(data)
    kurt = kurtosis(data)
    return mean_val, std_dev, median_val, iqr1, iqr3, skewness, kurt

def prepare_distribution_graph_data(properties_df, aggregates, visualize_options, bins, property_data):
    for aggregate in aggregates:
        aggregate_by, aggregate_with = aggregate.get('aggregateBy'), aggregate.get('aggregateWith')

        if not aggregate_by or not aggregate_with:
            continue

        if aggregate_by == 'City':
            properties_df = properties_df[properties_df['City'].str.contains(str(aggregate_with), case=False, na=False)]
        else:
            properties_df[aggregate_by] = properties_df[aggregate_by].astype(str)
            aggregate_with = str(aggregate_with)
            properties_df = properties_df[properties_df[aggregate_by] == aggregate_with]

    if properties_df.empty:
        return {"error": "No data found for the given parameters"}

    data_dict = {}
    annotations_dict = {}
    hist_data_dict = {}
    kde_data_dict = {}
    bin_widths = []
    percentiles = {}

    for visualize_by in visualize_options:
        data = properties_df[visualize_by]

        # Cap the data range to exclude extreme outliers
        lower_bound = np.percentile(data, 1)
        upper_bound = np.percentile(data, 99)
        data = data[(data >= lower_bound) & (data <= upper_bound)]

        mean_val, std_dev, median_val, iqr1, iqr3, skewness, kurt = calculate_statistics(data)
        
        # Use the provided number of bins
        num_bins = bins if bins > 0 else 10  # Default to 10 bins if not provided or invalid
        hist_data, bin_edges = np.histogram(data, bins=num_bins)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        bin_width = bin_edges[1] - bin_edges[0]

        histogram_data = [{"x": float(bin_centers[i]), "count": int(hist_data[i])} for i in range(len(hist_data))]

        # Prepare KDE data using bin centers for the x-axis
        kde = gaussian_kde(data, bw_method='scott')
        kde_vals = kde(bin_centers) * len(data) * bin_width  # Scale KDE values
        kde_data = [{"x": float(bin_centers[i]), "y": float(kde_vals[i])} for i in range(len(kde_vals))]

        # Calculate percentile
        property_value = property_data.get(visualize_by, None)
        if property_value is not None:
            percentile = np.sum(data < property_value) / len(data) * 100
            percentiles[visualize_by] = percentile

        # Store data in dictionaries
        data_dict[visualize_by] = data.tolist()
        annotations_dict[visualize_by] = {
            "mean": float(mean_val),
            "std_dev": float(std_dev),
            "median": float(median_val),
            "iqr1": float(iqr1),
            "iqr3": float(iqr3),
            "kurtosis": float(kurt),
            "skewness": float(skewness)
        }
        hist_data_dict[visualize_by] = histogram_data
        kde_data_dict[visualize_by] = kde_data
        bin_widths.append(float(bin_width))

    return {
        "data": data_dict,
        "annotations": annotations_dict,
        "histogram_data": hist_data_dict,
        "kde_data": kde_data_dict,
        "bin_widths": bin_widths,
        "percentiles": percentiles,
    }


###################
# CLUSTERING DATA #
###################

def calculate_umap_clusters(df, n_bins=8, sample_size=250, n_neighbors=15, min_dist=0.1, metric='euclidean'):
    """Calculates UMAP embeddings for the given DataFrame and assigns them to bins.

    Args:
        df: The input DataFrame.
        n_bins: The number of bins for clustering.
        sample_size: The number of samples to use for UMAP calculation.
        n_neighbors: The size of local neighborhood (in terms of number of neighboring sample points) used for manifold approximation.
        min_dist: The effective minimum distance between embedded points.
        metric: The metric to use for distance computation.

    Returns:
        A tuple of (umap_embeddings, bin_labels, bin_edges)
    """

    # Select only numeric columns
    numeric_df = df.select_dtypes(include=['int64', 'float32', 'float64'])

    # Sample the data if it exceeds the sample size
    if len(numeric_df) > sample_size:
        numeric_df = numeric_df.sample(sample_size, random_state=42)

    # Dimensionality reduction using UMAP with optimized parameters
    umap = UMAP(n_components=2, random_state=42, n_neighbors=n_neighbors, min_dist=min_dist, metric=metric)
    umap_embeddings = umap.fit_transform(numeric_df)

    # Calculate bin edges for both dimensions
    bin_edges_x = np.linspace(np.min(umap_embeddings[:, 0]), np.max(umap_embeddings[:, 0]), n_bins + 1)
    bin_edges_y = np.linspace(np.min(umap_embeddings[:, 1]), np.max(umap_embeddings[:, 1]), n_bins + 1)

    # Assign points to bins based on their coordinates
    bin_indices_x = np.digitize(umap_embeddings[:, 0], bin_edges_x, right=False) - 1
    bin_indices_y = np.digitize(umap_embeddings[:, 1], bin_edges_y, right=False) - 1

    # Create bin labels using list comprehensions
    bin_labels_x = [f"{bin_edges_x[i]:.2f}-{bin_edges_x[i+1]:.2f}" for i in range(n_bins)]
    bin_labels_y = [f"{bin_edges_y[i]:.2f}-{bin_edges_y[i+1]:.2f}" for i in range(n_bins)]

    return umap_embeddings, bin_labels_x, bin_labels_y, bin_indices_x, bin_indices_y

def prepare_clustering_graph_data(properties_df, sample_size=1000, n_neighbors=15, min_dist=0.1, metric='euclidean'):
    """Prepares clustering graph data.

    Args:
        properties_df: The DataFrame containing properties.
        sample_size: The number of samples to use for clustering calculations.
        n_neighbors: The size of local neighborhood (in terms of number of neighboring sample points) used for manifold approximation.
        min_dist: The effective minimum distance between embedded points.
        metric: The metric to use for distance computation.

    Returns:
        A dictionary containing UMAP embeddings.
    """

    umap_embeddings, bin_labels_x, bin_labels_y, bin_indices_x, bin_indices_y = calculate_umap_clusters(
        properties_df, n_bins=8, sample_size=sample_size, n_neighbors=n_neighbors, min_dist=min_dist, metric=metric
    )

    # Convert ndarrays to lists for JSON serialization
    result = {
        'umap_embeddings': umap_embeddings.tolist(),
        'bin_labels_x': bin_labels_x,
        'bin_labels_y': bin_labels_y,
        'bin_indices_x': bin_indices_x.tolist(),
        'bin_indices_y': bin_indices_y.tolist(),
    }

    return result


if __name__ == '__main__':
    pass

# About 

**K-NeuronSeg** is a neuron segmentation pipeline developed by [Kuan Lab](https://www.kuanlab.org/). This pipeline employs a chunked based mode for processing large-scale 3D EM data in neuron segmentation tasks. It is currently available as a CLI tool, supporting both local jobs and HPC jobs.

> Based on Linux machines with NVIDIA GPUs

It supports:

Deep learning based affinity maps inference
> Based on [PyTorch Connectomics](https://connectomics.readthedocs.io/en/latest/index.html).This is a deep learning framework for automatic and semi-automatic annotation of connectomics datasets, powered by [PyTorch](https://pytorch.org/).
- Pre-tain/fine-tune a DL model   
- Inference affinity map by blocks 
- Pre- and post-processing tools (spliting, merging)

Instance segmentation for affinity maps
- Affinity map blocking and independent segmentation  
- Aggregation of each blocked segmentation result 
- Pre- and post-processing tools (Conversion, downsampling, masking, et al.)


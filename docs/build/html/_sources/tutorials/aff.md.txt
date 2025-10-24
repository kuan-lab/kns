# Affinity Map Inference
This tutorial provides step-by-step guidance for affinity map inference pipeline.
> This section is integration and encapsulation of pytc. For more detailed, please refer to [pytc document](https://connectomics.readthedocs.io/en/latest/tutorials/neuron.html).

#### Main Menu

Run ```python -m K_NeuronSeg``` to start the CLI.

![Main](../_static/main.png)
The main interface consists of two functional modules: affinity map inference module and instance segmentation module.

Input ```1``` and ```Enter```, enter the **affinity map inference module**:
![affinity map inference module](../_static/aff.png)

 
#### Options

This module can be used for configuration, model pretraining, fine-tuning, inference, data preprocessing and postprocessing. 

- In pretraining: the model is pre-trained by inputting images and labeled images. This ultimately yields the pre-trained model parameters.

- In fine-tuning: for specific imaging data, fine-tune the model by inputting images and labeled images (often as mini-batches for a single bounding box). This process ultimately yields the final model parameters.

- In inference: inferring neuronal affinity maps for large-scale data using the final model.This process involves image blocking and stitching.

##### Global Configuration
Input ```9``` and ```Enter```, view current **global configuration**:
![global configuration](../_static/aff9.png)

For the title:
- ```Section```: the configuration file for which module.
- ```Parameter```: the key in configuration file.
- ```Value```: the value of key

For the keys in affinity map inference module:
- ```config_base```: the base config file path for pytc, details see [pytc document](https://connectomics.readthedocs.io/en/latest/tutorials/neuron.html).
- ```config_file```: the network config file path for pytc, details see [pytc document](https://connectomics.readthedocs.io/en/latest/tutorials/neuron.html).
- ```checkpoint```: the checkpoint path for fine-tuning and inference.
- ```hpc```: the hpc config file path.
- ```split```: the config file path for split tool.
- ```merge```: the config file path for merge tool.

> ***The meaning of each parameter is documented in every configuration file.***

Input ```8``` and ```Enter```, edit current **global configuration**:
> Currently, only modifications are permitted; additions are not allowed.

You can modify the current configuration file path.
![modify the current configuration file path](../_static/aff81.png)
And select a value to change:
![select a value to change](../_static/aff82.png)

##### Model pretraining
Input ```1``` and ```Enter```, using ***local resources*** to pre train a model. The model is based on the configuration files (```config_base``` and ``config_file``,  in global configuration file)

Input ```2``` and ```Enter```, using ***HPC resources*** to pre train a model. The model is based on the configuration files (```config_base```, ``config_file`` and ```hpc```,  in global configuration file)

Before start the training, you can modify the configuration:
![modify the configuration](../_static/aff11.png)

Then the pre-training will run automatically. 
> You can use ```Ctrl+C``` to stop it and Enter main menu.

![stop it](../_static/aff12.png)

When using ***HPC resources***, you need to configure the hpc and the job will submit to the hpc based on this configuration:
![modify the configuration](../_static/aff13.png)
You can change the parameters based on this CLI or ***directly modify the configuration file***.

##### Model fine-tuning
This process is essentially the same as pre-training, except that it adds the checkpoint configuration.

Input ```3``` and ```Enter```, using ***local resources*** to pre train a model. The model is based on the configuration files (```config_base```, ``config_file`` and ```checkpoint```,  in global configuration file)

Input ```4``` and ```Enter```, using ***HPC resources*** to pre train a model. The model is based on the configuration files (```config_base```, ``config_file``, ```checkpoint``` and ```hpc```,  in global configuration file)

##### Model inference
This section is optimized for large datasets. We first need to use the split tool to split large TIF/Precomputed images into multiple smaller blocks and save them in the same folder. Then, this module performs parallel processing on the segmented data. After completing all the inference, use the merge tool to stitch them together.

After encapsulation, the user experience remains consistent with the previous module:

Input ```5``` and ```Enter```, using ***local resources*** to pre train a model. The model is based on the configuration files (```config_base```, ``config_file`` and ```checkpoint```,  in global configuration file)

Input ```6``` and ```Enter```, using ***HPC resources*** to pre train a model. The model is based on the configuration files (```config_base```, ``config_file``, ```checkpoint``` and ```hpc```,  in global configuration file)

However, for HPC configuration files, this ```mutil_jobs``` switch must be enabled and the ```mutil_jobs_configs``` must be correct.
- ```configs_save_path```: subprofile storage location
- ```input_floder```: the path of blocks
- ```batch_num```: the number of blocks in parallel at once

##### Tools
Input ```7``` and ```Enter```, enter the **tool menu**:
![tool menu](../_static/tool.png)

Input ```1``` and ```Enter```, using ***local resources*** to split tif/precomputed volume to tif blocks with overlap. 

Input ```2``` and ```Enter```, using ***HPC resources*** to split tif/precomputed volume to tif blocks with overlap. 

The tool is based on the configuration files (```split``` in global configuration file).Before start the training, you can modify the configuration by CLI or any tools:
![split](../_static/tool1.png)

Input ```3``` and ```Enter```, using ***local resources*** to merge h5 blocks (inference) to tif/precomputed volume with overlap. 

Input ```4``` and ```Enter```, using ***HPC resources*** to merge h5 blocks (inference) to tif/precomputed volume with overlap. 

The tool is based on the configuration files (```merge``` in global configuration file).Before start the training, you can modify the configuration by CLI or any tools:
![merge](../_static/tool2.png)









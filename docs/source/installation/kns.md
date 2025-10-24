# Instance Segmentation
After installing conda, we need to configure K-NeuronSeg environment.
> Based on Linux machines with NVIDIA GPUs

#### Create a Virtual Environment

```bash
conda create -y -n kns python=3.9
conda activate kns
```

Install pytorch with right cuda version (for H100 or A100: usually 12.4):


```bash
conda install pytorch torchvision torchaudio pytorch-cuda=12.4 -c pytorch -c nvidia
```

#### Install K-NeuronSeg

##### Install All Modules
We have made modifications based on pytc (*version 0.1*). This section covers the basics of how to download and install this version. 
```bash
git clone https://github.com/kuan-lab/kns.git
cd kns
pip install --editable .

```

##### Install Affinity Maps Inference Module
You can also install each component independently.

```bash
git clone https://github.com/kuan-lab/kns.git
cd kns/pytorch_connectomics
pip install --editable .

# fix some dependency issues
pip install pillow==9.4.0
```

##### Install Waterz

```bash
git clone https://github.com/zudi-lin/waterz.git
cd waterz
pip install --editable .
pip install waterz
```

If error: “waterz/backend/types.hpp:3:10: fatal error: boost/multi_array.hpp: No such file or directory”
```bash
conda install boost
```

If error: 'PyDataType_ELSIZE' was not declared in this scope
```bash
pip install --upgrade numpy
```

If error: monai 1.4.0 requires numpy<2.0, >=1.24
After waterz installed
```bash
pip install numpy==1.26.4
```
 
If error: no module named “mahotas”
```bash
pip install mahotas
```




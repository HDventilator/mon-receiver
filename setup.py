import setuptools

setuptools.setup(
        name="mon-receiver",
        version="0.0.1",
        author="HDventilator",
        author_email="noreply@github.com",
        description="Ventilator serial receiver",
        url="https://github.com/HDventilator/mon-receiver",
        packages=setuptools.find_packages(),
        classifiers=[
            "Programming Language :: Python :: 3",
            "License :: OSI Approved :: MIT License",
            "Operating System :: OS Independent",
            ],
        python_requires=">=3.6",
        install_requires=[ # also see requirements.txt
            "cobs==1.1.3",
            "influxdb==5.3.0",
            "pyserial==3.4",
            ],
        include_package_data=True,
        )

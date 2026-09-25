from setuptools import setup, find_packages

setup(
    name="senaite.pfas",
    version="1.0.0",
    description="PFAS LIMS extension for SENAITE: method profiles, analyte "
                "library, barcode reagent tracking, run-queue QC review, "
                "extraction-driven reporting, and multi-vendor instrument import.",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="PFAS Lab",
    # GPLv2, matching the LICENSE file and the stack this extends. senaite.core,
    # senaite.lims and senaite.storage are all GPLv2 and are imported directly,
    # so this add-on is a derivative work and cannot be offered under a
    # permissive licence. Confirmed 2026-09-25; see DECISIONS.md.
    license="GPLv2",
    classifiers=[
        "Framework :: Plone",
        "Framework :: Zope2",
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
        "Programming Language :: Python :: 2.7",
        "Topic :: Scientific/Engineering :: Chemistry",
    ],
    packages=find_packages("src"),
    package_dir={"": "src"},
    namespace_packages=["senaite"],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "setuptools",
        # SENAITE core stack
        "senaite.lims>=2.6.0",
        "senaite.app.listing",
        "senaite.core>=2.6.0",
        # storage locations / sample storage
        "senaite.storage",
        # QR code generation for printed sample receipts (Python 2.7 compatible)
        "qrcode==6.1",
        # ReportLab PDF generation for extraction logbooks.
        # 3.0-3.3.x is the last series with full Python 2.7 support.
        # Must be installed separately (requires gcc + network for T1 fonts);
        # not declared here so it doesn't break buildout in minimal containers.
        # The @@pfas-extraction-pdf view handles ImportError gracefully.
        # "reportlab>=3.0,<3.4",
        # senaite.queue requires senaite.lims<2.0.0 and is incompatible with 2.x
        # senaite.patient is optional; omit unless clinical matrices are needed
        # pandas/pypdf/requests/pyyaml are worker-container deps only;
        # they live in requirements.txt and must not be declared here (Python 2.7)
    ],
    entry_points={
        "z3c.autoinclude.plugin": ["target = plone"],
    },
)

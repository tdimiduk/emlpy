with import <nixpkgs> {};
with pkgs.pythonPackages;

buildPythonPackage rec {
    name = "holopy";
    src = ".";
    buildInputs = [ pkgs.gfortran ];
    propagatedBuildInputs = [ ipython jupyter numpy scipy matplotlib pandas pyyaml pillow emcee gfortran h5py seaborn];
}
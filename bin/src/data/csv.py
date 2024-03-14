"""
This file contains the parser class for parsing an input CSV file which is the STIMULUS data format.

The file contains a header column row where column names are formated as is : 
name:category:type

name is straightforward, it is the name of the column
category corresponds to any of those three values : input, meta, or label. Input is the input of the deep learning model, label is the output (what needs to be predicted) and meta corresponds to metadata not used during training (could be used for splitting).
type corresponds to the data type of the columns, as specified in the types module. 

The parser is a class that takes as input a CSV file and a experiment class that defines data types to be used, noising procedures, splitting etc. 
"""

import polars as pl
from typing import Any, Tuple, Union
from functools import partial

class CsvHandler:
    """
    Meta class for handling CSV files.
    """
    def __init__(self, experiment: Any, csv_path: str) -> None:
        self.experiment = experiment
        self.csv_path = csv_path
        self.categories = self.check_and_get_categories()
        self.check_compulsory_categories_exist()
    
    def check_and_get_categories(self) -> list:
        """
        Returns the categories contained in the csv file.
        """
        with open(self.csv_path, 'r') as f:
            header = f.readline().strip().split(',')
        categories = []
        for colname in header:
            category = colname.split(":")[1].lower()
            if category not in ['input', 'label', 'split', 'meta']:
                raise ValueError(f"Unknown category {category}, category (the second element of the csv column, seperated by ':') should be input, label, split or meta. The specified csv column is {colname}.")
            categories.append(category)
        return categories
    
    def get_keys_based_on_name_category_dtype(self, column_name: str = None, category: str = None, data_type: str = None) -> list:
        """
        Returns the keys that are of a specific type, name or category. Or a combination of those.
        """
        if (column_name is None) and (category is None) and (data_type is None):
            raise ValueError(f"At least one of the arguments column_name, category or data_type should be provided")
        with open(self.csv_path, 'r') as f:
            header = f.readline().strip().split(',')
        keys = []
        for key in header:
            current_name, current_category, current_dtype = key.split(":")
            if (column_name is None or column_name == current_name) and (category is None or category == current_category) and (data_type is None or data_type == current_dtype):
                keys.append(key)
        if len(keys) == 0:
            raise ValueError(f"No keys found with the specified column_name={column_name}, category={category}, data_type={data_type}")
        return keys

    def check_compulsory_categories_exist(self) -> None:
        """
        Checks if the compulsory categories exist in the csv file.
        """
        if 'input' not in self.categories:
            raise ValueError(f"The category input is not present in the csv file")
    
    def load_csv(self) -> pl.DataFrame:
        """
        Loads the csv file into a polars dataframe.
        """
        return pl.read_csv(self.csv_path)


class CsvProcessing(CsvHandler):
    """
    Class to load the input csv data and add noise accordingly.
    """

    def __init__(self, experiment: Any, csv_path: str) -> None:
        super().__init__(experiment, csv_path)
        self.data = self.load_csv()
    
    def add_noise(self, configs: list) -> None:
        """
        Adds noise to the data.
        Noise is added for each column with the configurations specified in the configs list.
        """
        for dictionary in configs:
            key = dictionary['column_name']
            data_type = key.split(':')[2]
            noise_generator = dictionary['name']
            new_column = self.experiment.add_noise_all(data_type, noise_generator)(list(self.data[key]), **dictionary['params'])
            self.data = self.data.with_columns(pl.Series(key, new_column))

    def save(self, path: str) -> None:
        """
        Saves the data to a csv file.
        """
        self.data.write_csv(path)

    
class CsvLoader(CsvHandler):
    """
    Class for loading and splitting the csv data, and then encode the information.
    
    It will parse the CSV file into four dictionaries, one for each category [input, label, meta, split].
    So each dictionary will have the keys in the form name:type, and the values will be the column values.
    Afterwards, one can get one or many items from the data, encoded.
    """
    def __init__(self, experiment: Any, csv_path: str, split: Union[int, None] = None) -> None:
        """ 
        Initialize the class by parsing and splitting the csv data into the corresponding categories.

        args:
            experiment (class) : The experiment class to perform
            csv_path (str) : The path to the csv file
            split (int) : The split to load, 0 is train, 1 is validation, 2 is test.
        """
        super().__init__(experiment, csv_path)

        # we need a different parsing function in case we have the split argument or not
        # NOTE using partial we can define the default split value, without the need to pass it as an argument all the time through the class
        if split is not None:
            prefered_load_method = partial(self.load_csv_per_split, split=split)
        else:
            prefered_load_method = self.load_csv

        # parse csv and split into categories
        self.input, self.label, self.split, self.meta = self.parse_csv_to_input_label_split_meta(prefered_load_method)
    
    def load_csv_per_split(self, split: int) -> pl.DataFrame:
        """
        Load the part of csv file that has the specified split value.
        Split is a number that for 0 is train, 1 is validation, 2 is test.
        This is accessed through the column with category `split`. Example column name could be `split:split:int`.
        """
        if 'split' not in self.categories:
            raise ValueError(f"The category split is not present in the csv file")
        if split not in [0, 1, 2]:
            raise ValueError(f"The split value should be 0, 1 or 2. The specified split value is {split}")
        colname = self.get_keys_based_on_name_category_dtype("split")
        if len(colname) > 1:
            raise ValueError(f"The split category should have only one column, the specified csv file has {len(colname)} columns")
        colname = colname[0]
        return pl.scan_csv(self.csv_path).filter(pl.col(colname) == split).collect()
    
    def parse_csv_to_input_label_split_meta(self, load_method: Any) -> Tuple[dict, dict, dict]:
        """
        This function reads the csv file into a dictionary, 
        and then parses each key with the form name:category:type 
        into three dictionaries, one for each category [input, label, meta].
        The keys of each new dictionary are in this form name:type.
        """
        # read csv file into a dictionary of lists
        # the keys of the dictionary are the column names and the values are the column values
        data = load_method().to_dict(as_series=False)
        
        # parse the dictionary into three dictionaries, one for each category [input, label, split, meta]
        input_data, label_data, split_data, meta_data = {}, {}, {}, {}
        for key in data:
            name, category, data_type = key.split(":")
            if category.lower() == "input":
                input_data[f"{name}:{data_type}"] = data[key]
            elif category.lower() == "label":
                label_data[f"{name}:{data_type}"] = data[key]
            elif category.lower() == 'split':
                split_data[f"{name}:{data_type}"] = data[key]
            elif category.lower() == "meta":
                meta_data[f"{name}:{data_type}"] = data[key]
        return input_data, label_data, split_data, meta_data
    
    def get_and_encode(self, dictionary: dict, idx: Any) -> dict:
        """
        It gets the data at a given index, and encodes it according to the data_type.

        `dictionary`:
            The keys of the dictionaries are always in the form `name:type`.
            `type` should always match the name of the initialized data_types in the Experiment class. So if there is a `dna` data_type in the Experiment class, then the input key should be `name:dna`
        `idx`:
            The index of the data to be returned, it can be a single index, a list of indexes or a slice

        The return value is a dictionary containing numpy array of the encoded data at the given index.
        """
        output = {}
        for key in dictionary: # processing each column

            # get the name and data_type
            name = key.split(":")[0]
            data_type = key.split(":")[1]

            # get the data at the given index
            # if the data is not a list, it is converted to a list
            # otherwise it breaks Float().encode_all(data) because it expects a list
            data = dictionary[key][idx]
            if not isinstance(data, list):
                data = [data]

            # check if 'data_type' is in the experiment class attributes
            if not hasattr(self.experiment, data_type.lower()):
                raise ValueError(f"The data type {data_type} is not in the experiment class attributes. the column name is {key}, the available attributes are {self.experiment.__dict__}")
            
            # encode the data at given index
            # For that, it first retrieves the data object and then calls the encode_all method to encode the data
            output[name] = self.experiment.get_encoding_all(data_type)(dictionary[key][idx])

        return output
    
    def __len__(self) -> int:
        """
        returns the length of the first list in input, assumes that all are the same length
        """
        return len(list(self.input.values())[0])
    
    def __getitem__(self, idx: Any) -> dict:
        """
        It gets the data at a given index, and encodes the input and label, leaving meta as it is.
        """
        x = self.get_and_encode(self.input, idx)
        y = self.get_and_encode(self.label, idx)
        return x, y, self.meta
    
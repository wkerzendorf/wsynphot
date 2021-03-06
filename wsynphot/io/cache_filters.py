import os, re
import numpy as np
import logging

# tqdm.autonotebook automatically chooses between console & notebook
from tqdm.autonotebook import tqdm
from astropy.io.votable import parse_single_table

from wsynphot.io.get_filter_data import (get_filter_index,
    get_transmission_data)
from wsynphot.config import get_cache_dir, set_cache_updation_date

CACHE_DIR = get_cache_dir()
logger = logging.getLogger(__name__)


def cache_as_votable(table, file_path):
    """Caches the passed table on disk as a VOTable.

    Parameters
    ----------
    table : astropy.table.Table
        Table to be cached 
    file_path : str
        Path where VOTable is to be saved 
    """
    if not file_path.endswith('.vot'):
        file_path += '.vot'

    dir_path = os.path.dirname(file_path)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    # Write table as votable (overwrite for cases when file already exists)
    table.write(file_path, format='votable', overwrite=True)


def download_filter_data(cache_dir=CACHE_DIR):
    """Downloads the entire filter data (filter index and transmission data 
    of each filter) locally on disk as cache.

    Parameters
    ----------
    cache_dir : str, optional
        Path of the directory where downloaded data is to be cached 
    """
    # Get filter index and cache it
    logger.info("Caching filter index ...")
    index_table = get_filter_index().to_table()
    cache_as_votable(index_table,
        os.path.join(cache_dir, 'index'))
    set_cache_updation_date()

    # Fetch filter_ids from index & download transmission data
    logger.info("Caching transmission data ...")
    iterative_download_transmission_data(index_table['filterID'], cache_dir)


def download_transmission_data(filter_id, cache_dir=CACHE_DIR):
    """Downloads transmission data for the requested filter ID systematically  
    on disk as cache (in facility/instrument/ directory).

    Parameters
    ----------
    filter_id : str
        Filter ID in either wsynphot format: 'facilty/instrument/filter' 
        or SVO format: 'facilty/instrument.filter' (Can use '/' and '.' 
        interchangeably as delimiters)
    cache_dir : str, optional
        Path of the directory where downloaded data is to be cached 
    """
    facility, instrument, filter_name = re.split('/|\.', filter_id)
    # Convert filter_id in SVO format to get transmission data from SVO
    svo_filter_id = '{0}/{1}.{2}'.format(facility, instrument, filter_name)
    filter_table = get_transmission_data(svo_filter_id).to_table()

    cache_as_votable(filter_table, os.path.join(cache_dir, facility, 
        instrument, filter_name))


def iterative_download_transmission_data(filter_ids, cache_dir=CACHE_DIR):
    """Iteratively downloads transmission data for the passed filter IDs 
    iterator, by internally calling download_transmission_data(). It also 
    displays a progress bar with necessary information for the filters being 
    downloaded.

    Parameters
    ----------
    filter_ids: iterable
        Iterable object containing Filter IDs as str in either wsynphot format: 
        'facilty/instrument/filter' or SVO format: 'facilty/instrument.filter' 
        (Can use '/' and '.' interchangeably as delimiters)
    cache_dir : str, optional
        Path of the directory where downloaded data is to be cached 
    """
    # Decorate the iterator with progress bar
    filter_ids_pbar = tqdm(filter_ids, desc='Filter ID', total=len(filter_ids))

    # Iterate over each filter_id and download transmission data
    for filter_id in filter_ids_pbar:
        if isinstance(filter_id, bytes): # treat byte string
            filter_id = filter_id.decode("utf-8")

        filter_ids_pbar.set_postfix_str(filter_id)

        try:
            download_transmission_data(filter_id, cache_dir)
        except Exception as e:
            logger.error('Data for filter ID = {0} could not be downloaded '
                'due to:\n{1}'.format(filter_id, e))


def update_filter_data(cache_dir=CACHE_DIR):
    """Updates the cached filter data (filter index and transmission data) 
    by downloading new filters & removing outdated filters.

    Parameters
    ----------
    cache_dir : str, optional
        Path of the directory where cached filter data is present 
    
    Returns
    -------
    bool
        True if cache got updated, otherwise False for the case when cache is 
        already up-to-date
    """
    # Obtain all filter IDs from cache as old_filters
    old_index = load_filter_index(cache_dir)
    old_filters = old_index['filterID'].to_numpy()
    
    # Obtain all filter IDs from SVO FPS as new_filters
    logger.info("Fetching latest filter index ...")
    new_index = get_filter_index().to_table()
    new_filters = np.array(new_index['filterID'], dtype=str)

    # Check whether there is need to update
    if np.array_equal(old_filters, new_filters):
        logger.info('Filter data is already up-to-date!')
        set_cache_updation_date()
        return False

    # Iterate & remove (old_filters - new_filters) from cache
    filters_to_remove = np.setdiff1d(old_filters, new_filters)
    logger.info("Removing outdated filters ...")
    for filter_id in filters_to_remove:
        facility, instrument, filter_name = re.split('/|\.', filter_id)
        filter_file = os.path.join(cache_dir, facility, instrument,
        '{0}.vot'.format(filter_name))
        if os.path.exists(filter_file):
            os.remove(filter_file)
    remove_empty_dirs(cache_dir)
    
    # Iterate & download (new_filters - old_filters) into cache
    filters_to_add = np.setdiff1d(new_filters, old_filters)
    logger.info("Caching new filters ...")
    iterative_download_transmission_data(filters_to_add, cache_dir)

    # Overwrite new index in cache
    cache_as_votable(new_index, os.path.join(cache_dir, 'index'))
    set_cache_updation_date()
    return True


def load_filter_index(cache_dir=CACHE_DIR):
    """Loads filter index from the cached filter data present on disk as a
    pandas dataframe.

    Parameters
    ----------
    cache_dir : str, optional
        Path of the directory where downloaded data is to be cached 

    Returns
    -------
    pandas.core.frame.DataFrame
        Filter index loaded as a dataframe
    """
    filter_index_loc = os.path.join(cache_dir, 'index.vot')
    
    # When no index votable is present
    if not os.path.exists(filter_index_loc):
        raise IOError('Filter index does not exist in the cache directory: '
            '{0}\nMake sure you have already downloaded filter data by using '
            'download_filter_data()'.format(cache_dir))

    return df_from_votable(filter_index_loc)


def load_transmission_data(filter_id, cache_dir=CACHE_DIR):
    """Loads transmission data for requested Filter ID from the cached filter 
    data present on disk as a pandas dataframe.

    Parameters
    ----------
    filter_id : str
        Filter ID in either wsynphot format: 'facilty/instrument/filter' 
        or SVO format: 'facilty/instrument.filter' (Can use '/' and '.' 
        interchangeably as delimiters)
    cache_dir : str, optional
        Path of the directory where downloaded data is to be cached 

    Returns
    -------
    pandas.core.frame.DataFrame
        Filter's transmission data loaded as a dataframe
    """
    facility, instrument, filter_name = re.split('/|\.', filter_id)
    transmission_data_loc = os.path.join(cache_dir, facility, instrument,
        '{0}.vot'.format(filter_name))

    # When no such filter votable is present
    if not os.path.exists(transmission_data_loc):
        index = load_filter_index(cache_dir)
        # Check whether filter_id is present in index
        svo_filter_id = '{0}/{1}.{2}'.format(facility, instrument, filter_name)
        if svo_filter_id in index['filterID'].values:
            raise IOError('Requested filter ID: {0} exists in index, but its '
                'transmission data is missing in the cache directory: {1}\n'
                'Make sure you have downloaded complete filter data by using '
                'download_filter_data(). Or if you specifically want to '
                'download transmission data for only requested filter ID, '
                'use download_transmission_data()'.format(filter_id, 
                    cache_dir))
        else:
            raise ValueError('Requested filter ID: {0} does not '
                'exists'.format(filter_id))

    return df_from_votable(transmission_data_loc)


def df_from_votable(votable_path):
    """Parses the passed VOTable to produce data in a usable table format as 
    pandas dataframe.

    Parameters
    ----------
    votable_path : str
        Path where VOTable to be used is stored. Make sure passed VOTable is 
        properly formatted, since this is "not" a general purpose function.

    Returns
    -------
    pandas.core.frame.DataFrame
        Parsed data as a dataframe
    """
    table = parse_single_table(votable_path).to_table()
    df = table.to_pandas()
    return byte_to_literal_strings(df)


def byte_to_literal_strings(dataframe):
    """Converts byte strings (if any) present in passed dataframe to literal
    strings and returns an improved dataframe.
    """
    # Select the str columns:
    str_df = dataframe.select_dtypes([np.object])
    
    if not str_df.empty:
        # Convert all of them into unicode strings
        str_df = str_df.stack().str.decode('utf-8').unstack()
        # Swap out converted cols with the original df cols
        for col in str_df:
            dataframe[col] = str_df[col]
    
    return dataframe


def remove_empty_dirs(root_dir):
    """Removes empty directories if present in the passed directory"""
    for root, dirs, files in os.walk(root_dir, topdown=False):
        for dirname in dirs:
            dirpath = os.path.join(root, dirname)
            if not os.listdir(dirpath): # check whether the dir is empty
                os.rmdir(dirpath)
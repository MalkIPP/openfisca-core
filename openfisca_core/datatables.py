# -*- coding: utf-8 -*-


# OpenFisca -- A versatile microsimulation software
# By: OpenFisca Team <contact@openfisca.fr>
#
# Copyright (C) 2011, 2012, 2013, 2014 OpenFisca Team
# https://github.com/openfisca
#
# This file is part of OpenFisca.
#
# OpenFisca is free software; you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# OpenFisca is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


from __future__ import division

import collections
import logging

import numpy as np
from pandas import DataFrame, HDFStore, read_csv, Series

from . import model


log = logging.getLogger(__name__)


def _survey_subset(table, subset):
    '''
    Select a subset for the given table, selection only on idmen so far
    '''
    if subset is not None:
        idx_subset = table['idmen'].isin(subset)
        return table[idx_subset]
    else:
        return table


class DataTable(object):
    column_by_name = None

    def __init__(self, column_by_name, survey_data = None, scenario = None, datesim = None, num_table = 1, subset = None,
            print_missing = True):
        assert isinstance(column_by_name, collections.OrderedDict)
        self.column_by_name = column_by_name
        self.test_case = scenario
        self.decomp_file = None
        self.survey_data = survey_data
        self.num_table = num_table
        self.subset = subset

        self.table = DataFrame()
        self.table3 = {'ind' : DataFrame(), 'foy' : DataFrame(), 'men' : DataFrame()}

        self.index = {}
        self._nrows = 0
        self.print_missing = print_missing

        assert datesim is not None
        self.datesim = datesim

        self.list_entities = ['ind'] + model.ENTITIES_INDEX
        self.survey_year = None

    # The 2 following functions are created to tell pickle what to do when pickling and unpickling.

    def __getstate__(self):
        def should_pickle(k):
            return k not in ['table', 'table3', '_param', '_default_param']
        return dict((k, v) for (k, v) in self.__dict__.iteritems() if should_pickle(k))

    def __setstate__(self, d):
        self.__dict__ = d
        self.table = None
        self.table3 = None

    def load_data_from_test_case(self, test_case):
        self.test_case = test_case
        if test_case.nmen == 1:
            test_case.dummy_x_axis = True
            test_case.nmen = 2
            test_case.populate_datatable(self)
            del test_case.dummy_x_axis
            test_case.nmen = 1
        else:
            test_case.populate_datatable(self)


    def load_data_from_survey(self, survey_data,
                              num_table = 1,
                              subset = None,
                              print_missing = True):
        self.survey_data = survey_data
        self.populate_from_survey_data(survey_data)


    def gen_index(self, entities):
        '''
        Generates indexes for the relevant entities
        '''

        self.index = {'ind': {0: {'idxIndi':np.arange(self._nrows),
                                  'idxUnit':np.arange(self._nrows)},  # Units stand for entities
                      'nb': self._nrows}}

        for entity in entities:
            enum = self.column_by_name.get('qui' + entity).enum
            try:
                if self.num_table == 1:
                    idx = getattr(self.table, 'id' + entity).values
                    qui = getattr(self.table, 'qui' + entity).values
                elif self.num_table == 3:
                    idx = getattr(self.table3['ind'], 'id' + entity).values
                    qui = getattr(self.table3['ind'], 'qui' + entity).values

                enum = self.column_by_name.get('qui' + entity).enum
            except:
                log.error('DataTable needs columns %s and %s to build index with entity %s' % ('id' + entity,
                    'qui' + entity, entity))
                raise

            self.index[entity] = {}
            dct = self.index[entity]
            idxlist = np.unique(idx)

            if self.num_table == 3:
                if len(idxlist) != len(self.table3[entity]):
                    print "Warning: list of ident is not consistent for %s" % entity
                    print self.survey_year, len(idxlist), len(self.table3[entity])
                    idxent = self.table3[entity]['id' + entity]
                    # diff1 = set(idxlist).symmetric_difference(idxent)
                    if len(idxlist) > len(self.table3[entity]):
                        idxlist = idxent
                # Generates index for the entity of each individual
                self.index['ind'][entity] = np.searchsorted(idxlist, idx)

            dct['nb'] = len(idxlist)

            for full, person in enum:
                idxIndi = np.sort(np.squeeze((np.argwhere(qui == person))))
#                if (person == 0) and (dct['nb'] != len(idxIndi)):
#                    raise Exception('Invalid index for %s: There is %i %s and %i %s' %(entity, dct['nb'], entity, len(idxIndi), full))
                idxUnit = np.searchsorted(idxlist, idx[idxIndi])
                temp = {'idxIndi':idxIndi, 'idxUnit':idxUnit}
                dct.update({person: temp})

        if self.num_table == 3:
        # add index of men for intermediate entities
        # TODO: make it generel with level of entity
            for entity in entities:
                for super_entity in entities :
                    if super_entity != entity:
                        head = self.index[entity][0]['idxIndi']
                        self.index[entity][super_entity] = self.index['ind'][super_entity][head]

    def propagate_to_members(self, varname, entity):
        """
        if entity is 'ind': Set the variable of all individual to the value of the (head of) entity
        else              : Set the varible of all entity to the value of the enclosing entity of varname
        """
        col = self.column_by_name.get(varname)
        from_ent = col.entity
        value = self.get_value(varname)
        if self.num_table == 1:
            try:
                enum = self.column_by_name.get('qui' + from_ent).enum
            except:
                enum = self._inputs.column_by_name.get('qui' + from_ent).enum
            head = self.index[from_ent][0]['idxIndi']
            for member in enum:
                value_member = value[head]
                select_unit = self.index[from_ent][member[1]]['idxUnit']
                value_member = value_member[select_unit]
                if varname != 'wprm':
                    self.set_value(varname, value_member, from_ent, opt = member[1])

        elif self.num_table == 3:
            # Should be useless
            return self._get_value3(varname, entity = entity, opt = range(10))

#             from_ent = col.entity
#             idx_to = self.index[entity]
#             if entity == 'ind':
#                 if from_ent == 'ind':
#                     raise Exception('Why propagate %s which is already an "ind" entity ' % (varname))
#                 else:
#                     idx_to = idx_to[from_ent]
#                     return value[idx_to]
#             else:
#                 if from_ent != 'men':
#                     raise Exception('Impossible to propagate %s which is not a "men" entity to %s'
#                     'because there is no inclusion between fam and foy' % (varname, entity))
#                 else:
#                     # select head of entity and look for their from_ent number
#                     head = idx_to[0]['idxIndi']
#                     idx_from = self.index['ind'][from_ent][head]
#                     return value[idx_from]



    def populate_from_survey_data(self, fname, year = None):
        '''
        Populates a DataTable from survey data
        '''
        INDEX = model.ENTITIES_INDEX
        list_entities = self.list_entities

        if isinstance(fname, str) or isinstance(fname, unicode):
            if fname[-4:] == '.csv':
                # TODO: implement it for _num_table==3 (or remove)
                if self.num_table == 1 :
                    with open(fname) as survey_data_file:
                        self.table = read_csv(survey_data_file)
                else :
                    raise Exception('For now, use three csv table is not allowed'
                                    'although there is no major difficulty. Please,'
                                    'feel free to code it')

            elif fname[-3:] == '.h5':
                store = HDFStore(fname)
                if self.num_table == 1 :
                    available_years = sorted([int(x[-4:]) for x in  store.keys()])
                elif self.num_table == 3 :
                    available_years = (sorted([int(x[-8:-4]) for x in  store.keys()]))
                # note+ we have a repetition here in available_years but it doesn't matter

                if year is None:
                    if self.datesim is not None:
                        year_ds = self.datesim.year
                    else:
                        raise Exception('self.datesim or year should be defined')
                else:
                    year_ds = year

                yr = year_ds + 0  # to avoid pointers problem
                while yr not in available_years and yr > available_years[0]:
                    yr = yr - 1
                base_name = 'survey_' + str(yr)
                if year_ds != yr:
                    print 'Survey data for year %s not found. Using year %s' % (str(year_ds), str(yr))
                else:
                    print 'Survey data for year %s found' % str(year_ds)

                if yr in available_years:
                    self.survey_year = yr


                if self.num_table == 1 :
                    self.table = _survey_subset(store[str(base_name)], self.subset)

                elif self.num_table == 3 :
                    for entity in self.list_entities:
                        self.table3[entity] = _survey_subset(store[str(base_name) + '/' + entity], self.subset)
                store.close()

        else:
            if self.num_table == 1:
                if not isinstance(fname, DataFrame):
                    raise Exception("When num_table=1, the object given as survey data must be a pandas DataFrame")
                else:
                    self.table = _survey_subset(fname, self.subset)
            elif self.num_table == 3:
                try:
                    for entity in list_entities:
                        assert isinstance(fname[entity], DataFrame)
                        self.table3[entity] = _survey_subset(fname[entity], self.subset)
                except:
                    log.error("When num_table=3, the object given as survey data"
                        " must be a dictionary of pandas DataFrame with each entity in keys")
                    raise

        missing_col = []
        var_entity = {}
        if self.num_table == 1 :
            self._nrows = self.table.shape[0]
            # Intialize to default value the missing variables
            for col in self.column_by_name.itervalues():
                if col.name not in self.table:
                    missing_col.append(col.name)
                    self.table[col.name] = col._default
                try:
                    if self.table[col.name].isnull().any():
                        self.table[col.name].fillna(col._default, inplace = True)
                    self.table[col.name] = self.table[col.name].astype(col._dtype)
                except:
                    log.error("Impossible de lire la variable suivante issue des données d'enquête :\n%s\n" % col.name)
                    raise
            # Keeping only valid input variables
            drop_variables = list(set(self.table.columns) - set(self.column_by_name.keys()))
            self.table.drop(drop_variables, inplace = True, axis = 1)

        elif self.num_table == 3 :
            self._nrows = self.table3['ind'].shape[0]
            for ent in list_entities:
                var_entity[ent] = [x for x in self.column_by_name.itervalues() if x.entity == ent]
                for col in var_entity[ent]:
                    if not col.name in self.table3[ent]:
                        missing_col.append(col.name)
                        self.table3[ent][col.name] = col._default
                    if self.table3[ent][col.name].isnull().any():
                        self.table3[ent][col.name].fillna(col._default, inplace = True)
                    self.table3[ent][col.name] = self.table3[ent][col.name].astype(col._dtype)
                if ent == 'foy':
                    self.table3[ent] = self.table3[ent].to_sparse(fill_value = 0)

        if missing_col:
            message = "%i input variables missing\n" % len(missing_col)
            messagef = ""
            messageb = ""
            missing_col.sort()
            for var in missing_col:
                if var[0] == 'f':
                    messagef += '  - ' + var + '\n'
                elif var[0] == 'b':
                    messageb += '  - ' + var + '\n'
                else:
                    message += '  - ' + var + '\n'
            if self.print_missing:
                print Warning(message + messagef + messageb)

        for var in INDEX:
            if ('id' + var) in missing_col:
                raise Exception('Survey data needs variable %s' % ('id' + var))

            if ('qui' + var) in missing_col:
                raise Exception('Survey data needs variable %s' % ('qui' + var))

        self.gen_index(INDEX)

        # Initialize default weights
#        self.set_value(model.WEIGHT_INI, self.get_value(model.WEIGHT), 'ind')

#        # TODO: activate for debug
#        print self.table.get_dtype_counts()
#
#        for col in self.table.columns:
#            if col not in self.column_by_name:
#                print 'removing : ',  col
#                del self.table[col]
#
#        print self.table.get_dtype_counts()

    def get_value(self, varname, entity = None, opt = None, sum_ = False, freqs = None):
        if self.num_table == 1:
            try:
                value = self._get_value1(varname, entity = entity, opt = opt, sum_ = sum_)
            except Exception, e:
                raise Exception("Problem error when getting variable %s : \n %s" % (varname, e))
#            if as_dataframe:
#                index_varname = "id" + entity # TODO: this is dirty
#                if sum_ is True:
#                    index_value = self._get_value1(index_varname, entity = entity, opt = None, sum_ = None)
#                return DataFrame({index_varname: index_value,  varname: value})
#            else:
            return value

        if self.num_table == 3:
            return self._get_value3(varname, entity = entity, opt = opt, sum_ = sum_)

    def _get_value1(self, varname, entity = None, opt = None, sum_ = False):
        '''
        Read the value in an array

        Parameters
        ----------
        entity : str, default None
                 if "ind" or None return every individual, else return individuals belongig to the entity
        opt : dict
             dict with the id of the person for which you want the value
            - if opt is None, returns the value for the person 0 (i.e. 'vous' for 'foy', 'chef' for 'fam', 'pref' for 'men' in the "france" case)
            - if opt is not None, return a dict with key 'person' and values for this person

        Returns
        -------
        sumout: array

        '''
        col = self.column_by_name.get(varname)
        dflt = col._default
        dtyp = col._dtype
        ent = col.entity
        var = np.array(self.table[varname].values, dtype = col._dtype)

        if entity is None:
            entity = "ind"

        if entity == "ind":
            if varname != 'ppe_coef':
            # should be : if ent == 'ind':
                return var
            else:
                # TODO: FIX THIS
                # print ("The %s entity variable %s, is called to set an individual variable"
                #               % (col.entity,varname))

                # ce qui suit est copie sur propagate_to_members
                value = self.get_value(varname, ent)
                try:
                    enum = self.column_by_name.get('qui' + ent).enum
                except:
                    enum = self._inputs.column_by_name.get('qui' + ent).enum
                for member in enum:
                    qui = member[1]
                    idx = self.index[ent][qui]
                    var[idx['idxIndi']] = value[idx['idxUnit']]
                return var

        nb = self.index[entity]['nb']
        if opt is None:
            temp = np.ones(nb, dtype = dtyp) * dflt
            idx = self.index[entity][0]
            temp[idx['idxUnit']] = var[idx['idxIndi']]
            return temp
        else:
            out = {}
            for person in opt:
                temp = np.ones(nb, dtype = dtyp) * dflt
                idx = self.index[entity][person]
                temp[idx['idxUnit']] = var[idx['idxIndi']]
                out[person] = temp
            if sum_ is False:
                if len(opt) == 1:
                    return out[opt[0]]
                else:
                    return out
            else:
                sumout = 0
                for val in out.itervalues():
                    sumout += val
                return sumout

    def _get_value3(self, varname, entity = None, opt = None, sum_ = False):
        '''
        Read the value in an array and return it in an appropriate format

        There are three different cases.
            1 - you just want to read the variable and use it at the same entity level
            2 - you want to propagate a variable of a big entity to one ore many members
            3 - you want to read variable for a small entity in a bigger one. In that case you may want:
                a) select data of particular individual (VOUS and CONJ for example)
                    in that case a dictonnary is return iff more than one person is given
                b) sum values of given individuals
        Note: an entity is said bigger than an other one every unit contains people of the same unit of the smaller one

        Parameters
        ----------
        entity : str, default None
                format of the output. The returned array size is always the entity size.
                - if None, output entity is the input one : entity of varname
#                 - if "ind" or None return every individual, else return individuals belonging to the entity
#                 - if entity not the natural value for varname, sum over all members of entity who are
#                  qui+'col.entity'==0

        opt : dict
             dict with the id of the person for which you want the value in entity
               - In case 2, it allows to propagate value from the big entity to only selected
                 individual (in general). Works only if entity='ind'
                  - if None, go to head of entity, even if am not happy with that, #
                    according to me, it should be more explicit
               - In case 3,
                    - if opt is None, returns the value for the person 0 (i.e. 'vous' for 'foy', 'chef' for 'fam', 'pref' for 'men' in the "france" case)
                    - if length opt is one, returns the value for that person
                    - if opt is not None and its length is more than one, return a dict with key 'person' and values for this person in each entity

        sum_ : bool
            Works only in case 3, but is the only case you may need it
               - If True, then default opt is all.
               - sum over people in opt

        Returns
        -------
        sumout: array

        '''
        # caracteristics of varname
        col = self.column_by_name.get(varname)
        dflt = col._default
        dtyp = col._dtype
        dent = col.entity
        var = np.array(self.table3[dent][varname].values, dtype = col._dtype)

        case = 0
        # TODO: Have a level of entities in the model description
        # for example, in France case, ind = 0, fam and foy =1 and men = 2, ind< fam,foy<men <- JS: Quid des gens
        # qui ont quitté le domicile familial mais qui déclarent avec leur parents ?
        # you can check than if entity is fam or foy and dent the other one then case still zero.
        if entity is None or entity == dent:
            case = 1
        elif entity == 'ind' or dent == 'men':  # level entity < level dent
            case = 2
        elif entity == 'men' or dent == 'ind':  # level entity > level dent
            case = 3
        if case == 0 and opt is None:
            case = 2
        if opt is not None and case == 1:
            if varname[:2] != 'id':
                print varname, dent, entity
                raise Exception("opt doesn't mean anything here %s" % varname)
            else:
                opt = None
        if opt is not None and case == 2 and entity is not 'ind':
            raise Exception("opt doesn't mean anything here : % s. there is no person in %s "
            "so opt is inconsistant " % (varname, entity))
        if sum_ == True and case != 3:
            # TODO: look why sometime it's sum_ is True here
            # raise Exception("Impossible to sum here %s over entity %s" % (varname, entity))
            sum_ = False
        if case == 3 and dent != 'ind' and opt is None :
            sum_ = True
        if case == 3 and opt is None:
            opt = [0]
        if varname == 'wprm' and entity == 'ind':
            opt = range(0, 10)

        if case == 1 :
            idx = self.index[dent][0]['idxUnit']  # here dent = entity
            return var[idx]

        elif case == 2 :
            nb = self.index[entity]['nb']
            temp = np.ones(nb, dtype = dtyp) * dflt
            # we have a direct index from ind to entity
            if opt is None :
                if entity != 'ind':
                    idx = self.index[dent][entity]
                    temp[idx] = var
                    # TODO: add a paramater to propagate to member or make it the default option ond put opt = 0 otherwise
                    if varname in ['so', 'zone_apl', 'loyer', 'wprm']:
                        idx_from = self.index[entity][dent]
                        temp = var[idx_from]
                    return temp
                # TODO: add opt everywhere and remove that if else
                else:
                    head = self.index[dent][0]
                    temp[head['idxIndi']] = var
                    return temp
            else:
                # here if opt is not None, we know we are dealing with entity = 'ind'
                for person in opt:
                    idx_person = self.index[dent][person]
                    temp[idx_person['idxIndi']] = var[idx_person['idxUnit']]
                return temp

        elif case == 3 :
            # Note: Here opt should not be None
            # Note: Here, entity = men or
            out = {}
            nb = self.index[entity]['nb']
            if dent == 'ind':
                for person in opt:
                    if sum_ is False:
                        temp = np.ones(nb, dtype = dtyp) * dflt
                    else :
                        temp = np.zeros(nb, dtype = dtyp)
                    idx = self.index[entity][person]
                    temp[idx['idxUnit']] = var[idx['idxIndi']]
                    out[person] = temp

                if sum_ is False:
                    if len(opt) == 1:
                        return out[opt[0]]
                    else:
                        return out
                else:
                    sum_out = 0
                    for val in out.itervalues():
                        sum_out += val
                    return sum_out

            else:
                # from foy or fam to men
                # Here we assume that sum_ is True
                if sum_ is False:
                    raise Exception("Cannot do anything but a sum from intermediate entity to the biggest one")
                temp = np.ones(nb, dtype = dtyp) * dflt
                idx_to = self.index[dent][entity]
                tab = self.table3[dent][varname]  # same as var but in pandas
                if isinstance(tab[0], bool):
                    print "Warning: try to sum the boolean %s. How ugly is that? " % varname
                    # Note that we have isol = True (isol) iff there is at least one isol
                    tab = tab.astype('int')
                by_idx = tab.groupby(idx_to)
                idx_to_unique = np.unique(idx_to)
                try:
                    temp[idx_to_unique] = by_idx.aggregate(np.sum)
                except:
                    # TODO: always do the convertion but better to be explicit
                    values = by_idx.aggregate(np.sum).astype('bool')
                    temp[idx_to_unique] = values
                return temp


    def set_value(self, varname, value, entity = None, opt = None):
        '''
        Sets the value of varname using index and opt

        Parameters
        ----------
        varname: string,
                  variable to set
        value: TODO: fill
                  value assigned to varname
        entity: string, default None and if None entity is set to "ind"
                the specified entity
        opt: int
             position in the entity
        '''
        if entity is None:
            entity = "ind"

        if opt is None:
            idx = self.index[entity][0]
        else:
            idx = self.index[entity][opt]
        try:
            col = self.column_by_name.get(varname)
            dtyp = col._dtype
        except Exception as e:
            print e
            raise Exception('Error when getting column %s' % varname)

        if self.num_table == 1:
            values = Series(value[idx['idxUnit']], dtype = dtyp)
            self.table[varname][idx['idxIndi'].tolist()] = values  # tolist because sometime len(idx['idxIndi']) == 1
        elif self.num_table == 3:
            if entity == 'ind':
                self.table3[entity].ix[idx['idxIndi'], [varname]] = value
            else:
                self.table3[entity].ix[idx['idxUnit'], [varname]] = value


    # TODO:
    def to_pytables(self, fname):
        NotImplementedError

    def to_csv(self, fname):
        self.table.to_csv(fname)

    def __str__(self):
        return self.table.__str__()

    def inflate(self, varname, inflator):
        self.table[varname] = inflator * self.table[varname]

from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, SubmitField, IntegerField, DecimalField, SelectField
from wtforms.validators import DataRequired, NumberRange, ValidationError
from retrobiocat_web.retro.generation import node_analysis
from retrobiocat_web.retro.enzyme_identification import query_mongodb

def is_accepted_by_rdkit(form, field):
    if node_analysis.rdkit_smile(field.data) == None:
        if field.data != '':
            raise ValidationError('SMILES not accepted by rdkit')

def is_reaction(form, field):
    reaction_names = list(field.data.split(", "))
    for reaction in reaction_names:
        if reaction not in (query_mongodb.get_reactions_in_db() + ['All']):
            if reaction != '':
                raise ValidationError('Reaction not defined in main_site')

def is_enzyme(form, field):
    enzyme_names = list(field.data.split(", "))
    for enzyme in enzyme_names:
        if enzyme not in (query_mongodb.get_enzymes_in_db() + ['All']):
            if enzyme != ['']:
                raise ValidationError('Enzyme not defined in main_site')

substrate_node_choices = [('Starting material', 'Starting material'),
                          ('Relative complexity', 'Relative complexity'),
                          ('Off', 'Off')]

enzyme_node_choices = [('Substrate specificity', 'Substrate specificity'),
                       ('Complexity change', 'Complexity change'),
                        ('Off', 'Off')]

edges_choices = [('Off', 'Off'), ('Complexity change', 'Complexity change')]

score_substrates = [('Product only', 'Product only'), ('Product + substrates (slower)', 'Product + substrates (slower)')]

class NetworkExploreForm(FlaskForm):
    target_smiles = StringField('Target SMILES', validators=[DataRequired(), is_accepted_by_rdkit])
    number_steps = IntegerField('Initial steps', default=1, validators=[NumberRange(min=0, max=10)])
    max_initial_nodes = IntegerField('Max initial nodes', default=20, validators=[NumberRange(min=1, max=80)])
    max_reactions = IntegerField('Max reactions', default=10, validators=[NumberRange(min=0, max=50)])
    allow_backwards = BooleanField('Allow backwards steps')
    remove_small = BooleanField('Remove small molecules (eg NH3)', default=True)
    combine_enantiomers = BooleanField('Combine enantiomers for racemic starting material', default=True)
    include_experimental = BooleanField('Include experimental reaction rules', default=False)
    include_two_step = BooleanField('Include reaction rules for multi-step reactions, which are also included as single step rules', default=True)
    include_requires_absence_of_water = BooleanField('Include reactions which require an absence of water', default=False)
    only_reviewed = BooleanField('Use only reviewed substrate specificity data', default=False)
    calc_complexity = BooleanField('Calculate molecular complexity (slower)', default=True)
    sub_sim = BooleanField('Calculate substrate specificity (slower)', default=True)
    sub_thres = DecimalField('Substrate similarity threshold', default=0.5, validators=[NumberRange(min=0, max=1)])
    specificity_scoring_mode = SelectField('Specificity scoring mode', choices=score_substrates)
    colour_reactions = SelectField('Colour reaction nodes', choices=enzyme_node_choices)
    colour_edges = SelectField('Colour edges', choices=edges_choices)
    show_neg_enz = BooleanField('Show negative enzyme specificity', default=True)
    submit = SubmitField('Start')

class PathwayExploreForm(FlaskForm):
    target_smiles = StringField('Target SMILES', validators=[DataRequired(), is_accepted_by_rdkit])
    number_steps = IntegerField('Max steps', default=4, validators=[NumberRange(min=1, max=5)])
    weight_complexity = IntegerField('Weight Complexity Change', default=1, validators=[NumberRange(min=-1, max=10)])
    weight_num_enzymes = IntegerField('Weight Number of Enzymes', default=1, validators=[NumberRange(min=-1, max=10)])
    weight_starting = IntegerField('Weight Starting Material', default=1, validators=[NumberRange(min=-1, max=10)])
    weight_known_enzymes = IntegerField('Weight Known Enzyme Steps', default=1, validators=[NumberRange(min=-1, max=10)])
    weight_diversity = IntegerField('Weight Diversity', default=1, validators=[NumberRange(min=-1, max=10)])
    remove_small = BooleanField('Remove small molecules (eg NH3)', default=True)
    combine_enantiomers = BooleanField('Combine enantiomers for racemic starting material', default=True)
    include_experimental = BooleanField('Include experimental reaction rules', default=False)
    include_requires_absence_of_water = BooleanField('Include reactions which require an absence of water', default=False)
    only_reviewed = BooleanField('Use only reviewed substrate specificity data', default=False)
    include_two_step = BooleanField('Include reaction rules for multi-step reactions, which are also included as single step rules', default=True)
    sub_thres = DecimalField('Substrate similarity threshold', default=0.6, validators=[NumberRange(min=0, max=1)])
    specificity_scoring_mode = SelectField('Specificity scoring mode', choices=score_substrates)
    show_neg_enz = BooleanField('Show negative enzyme specificity', default=True)
    colour_reactions = SelectField('Colour reaction nodes', choices=enzyme_node_choices)
    colour_edges = SelectField('Colour edges', choices=edges_choices)
    max_nodes = IntegerField('Max nodes', default=400, validators=[NumberRange(min=100, max=800)])
    max_pathways = IntegerField('Max pathways', default=40000, validators=[NumberRange(min=100, max=80000)])
    keep_best_pathways = IntegerField('Max pathways', default=2500, validators=[NumberRange(min=50, max=100000)])
    min_weight = DecimalField('Min complexity weight', default=1, validators=[NumberRange(min=0.1, max=2)])
    hierarchical =  BooleanField('Heirarchical node layout')
    submit = SubmitField('Start')

specificity_data_choices = [('All', 'All'),
                            ('Categorical', 'Categorical'),
                            ('Quantitative', 'Quantitative'),
                            ('Specific Activity', 'Specific Activity'),
                            ('Conversion', 'Conversion')]

class SubstrateForm(FlaskForm):
    enzymes = StringField('Enzymes', validators=[DataRequired(), is_enzyme])
    reactions = StringField('reactions', validators=[is_reaction])
    data_level = SelectField('Data level', choices=specificity_data_choices)
    num_choices = IntegerField('Max enzymes per substrate', default=1, validators=[NumberRange(min=1, max=100)])
    max_hits = IntegerField('Max number of substrates', default=10, validators=[NumberRange(min=1, max=100)])
    product = StringField('Product SMILES', validators=[is_accepted_by_rdkit])
    similarity = DecimalField('Similarity cutoff', default=0.6, validators=[NumberRange(min=0.1, max=1)])
    only_reviewed = BooleanField('Only reviewed data', default=False)
    submit = SubmitField('Submit')

class Network_Vis_Options(FlaskForm):
    colour_substrates = SelectField('Colour substrate nodes', choices=substrate_node_choices)
    colour_reactions = SelectField('Colour reaction nodes', choices=enzyme_node_choices)
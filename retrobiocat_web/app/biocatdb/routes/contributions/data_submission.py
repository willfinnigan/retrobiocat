from retrobiocat_web.app.biocatdb import bp
from flask import render_template, flash, redirect, url_for, request, jsonify, session
from flask_security import roles_required, current_user
from retrobiocat_web.mongo.models.user_models import User, Role
from retrobiocat_web.mongo.models.biocatdb_models import EnzymeType, Sequence, Activity, Paper, ActivityMol
from retrobiocat_web.mongo.models.reaction_models import Reaction
from retrobiocat_web.app.app import user_datastore
import json
import numpy as np
from retrobiocat_web.app.biocatdb.functions.papers import papers_functions
from retrobiocat_web.app.biocatdb.functions.activity import check_activity_data, cascade_activity_data
import mongoengine as db
from retrobiocat_web.app.biocatdb.functions.papers import paper_status
from retrobiocat_web.app.biocatdb.functions import check_permission
from retrobiocat_web.app.biocatdb.functions import sequence_table
from retrobiocat_web.app.biocatdb.functions.substrate_specificity import process_activity_data
from natsort import natsorted, ns

def get_paper_molecules(paper):
    mols = ActivityMol.objects(db.Q(paper=paper)).order_by('name')

    mol_list = []
    for mol in mols:
        mol_list.append((mol.name, mol.smi, mol.svg, str(mol.id)))

    mol_list = natsorted(mol_list, key=lambda x: x[0])

    return mol_list

def get_activity_data(paper):
    include = ['id', "reaction", "enzyme_name", "substrate_1_smiles", "substrate_2_smiles",
               "product_1_smiles", "temperature", "ph", "solvent", "other_conditions",
               "notes", "reaction_vol", "formulation", "biocat_conc", "kcat", "km",
               "mw", "substrate_1_conc", "substrate_2_conc", "specific_activity",
               "conversion", "conversion_time", "selectivity", "categorical", "binary",
               ]
    q_paper = db.Q(paper=paper)
    q_not_automated = db.Q(auto_generated__ne=True)

    activity_data = list(Activity.objects(q_paper & q_not_automated).only(*include).as_pymongo())
    for i, data in enumerate(activity_data):
        activity_data[i]['_id'] = str(activity_data[i]['_id'])
        if activity_data[i]['binary']:
            activity_data[i]['binary'] = 1
        else:
            activity_data[i]['binary'] = 0

    return activity_data

def get_paper_data(paper, user):
    self_assigned = ''
    other_user = ''
    if paper.owner == user:
        self_assigned = 'checked'
    elif paper.owner is not None and paper.owner != '':
        other_user = 'disabled'

    paper_owner_name = 'None'
    if paper.owner is not None:
        paper_owner_name = f"{paper.owner.first_name} {paper.owner.last_name}, {paper.owner.affiliation}"

    paper_dict = {'short_cit': paper.short_citation,
                  'doi': paper.doi,
                  'date': paper.date,
                  'title': paper.title,
                  'journal': paper.journal,
                  'authors': papers_functions.list_to_string(paper.authors),
                  'tags': papers_functions.list_to_string(paper.tags),
                  'self_assigned': self_assigned,
                  'disable_for_other_user': other_user,
                  'id': paper.id,
                  'paper_owner_name': paper_owner_name}

    return paper_dict

def get_status(paper, user):
    paper_progress_text, paper_progress = paper_status.paper_metadata_status(paper)
    sequence_progress_text, sequence_progress = paper_status.sequences_status(paper)
    activity_progress_text, activity_progress = paper_status.activity_status(paper)
    status, status_colour = paper_status.get_status(paper_progress, sequence_progress, activity_progress, paper)

    paper.status = status
    paper.save()

    status_dict = {'review_checked': '',
                   'review_disabled': 'disabled',
                   'reviewed_by': '',
                   'issues_checked': '',
                   'issues_hidden': 'hidden',
                   'importance_checked': '',
                   'importance_hidden': 'hidden',
                   'status': status,
                   'status_colour': status_colour,
                   'paper_progress': paper_progress,
                   'paper_progress_text': paper_progress_text,
                   'sequences_progress': sequence_progress,
                   'sequences_progress_text': sequence_progress_text,
                   'activity_progress': activity_progress,
                   'activity_progress_text': activity_progress_text}

    if current_user.has_role('super_contributor'):
        status_dict['review_disabled'] = ''
        status_dict['issues_hidden'] = ''
        status_dict['importance_hidden'] = ''
    if current_user.has_role('enzyme_champion'):
        for tag in paper.tags:
            if tag in user.enzyme_champion:
                status_dict['review_disabled'] = ''
                status_dict['issues_hidden'] = ''
                status_dict['importance_hidden'] = ''
    if paper.reviewed_by != None:
        rb = paper.reviewed_by
        status_dict['reviewed_by'] = f"{rb.first_name} {rb.last_name}, {rb.affiliation}"


    if paper.reviewed == True:
        status_dict['review_checked'] = 'checked'
    if paper.has_issues == True:
        status_dict['issues_checked'] = 'checked'
        status_dict['issues_hidden'] = ''
    if paper.high_importance == True:
        status_dict['importance_checked'] = 'checked'
        status_dict['importance_hidden'] = ''

    return status_dict

def get_comments(paper, user):
    comments = []
    for comment in paper.comments:
        comment_can_edit = False
        comment_can_delete = False
        if current_user.has_role('rxn_rules_admin') or comment.owner == user:
            comment_can_edit = True
            comment_can_delete = True

        new_comment = {'user': f"{comment.owner.first_name} {comment.owner.last_name}, {comment.owner.affiliation}",
                       'date': comment.date.strftime("%d/%m/%Y, %H:%M:%S"),
                       'comment': comment.text,
                       'comment_id': str(comment.id),
                       'can_edit': comment_can_edit,
                       'can_delete': comment_can_delete
                       }
        comments.append(new_comment)

    return comments

def get_admin_dict(paper):
    admin_dict = {}

    contributor_choices = [(f"{c.first_name} {c.last_name}", str(c.id)) for c in User.contributors()]
    admin_dict['contributors'] = [('Unassigned', '')] + contributor_choices

    if paper.owner != None:
        admin_dict['owner'] = str(paper.owner.id)
    else:
        admin_dict['owner'] = ''

    return admin_dict

@bp.route('/submission_main_page/<paper_id>', methods=['GET'])
@roles_required('contributor')
def submission_main_page(paper_id):
    user = user_datastore.get_user(current_user.id)
    paper_query = Paper.objects(id=paper_id).select_related()
    if len(paper_query) == 0:
        flash('Paper has not been added yet, please add to the database first', 'fail')
        return redirect(url_for("biocatdb.launch_add_paper"))

    paper = paper_query[0]

    if not check_permission.check_paper_permission(current_user.id, paper):
        flash('No access to edit this entry', 'fail')
        return redirect(url_for("biocatdb.launch_add_paper"))

    paper_data = get_paper_data(paper, user)
    activity_data = get_activity_data(paper)
    reactions = list(Reaction.objects().distinct('name'))
    enzyme_names = list(Sequence.objects(papers=paper).distinct('enzyme_name'))
    enzyme_types = list(EnzymeType.objects().distinct('enzyme_type'))
    enzyme_data = sequence_table.get_enzyme_data(db.Q(papers=paper))
    enzyme_types_in_paper = list(Sequence.objects(papers=paper).distinct('enzyme_type'))
    reactions_in_paper = list(Reaction.objects(enzyme_types__in=enzyme_types_in_paper).distinct('name'))
    reactions_in_activity = list(Activity.objects(paper=paper).distinct('reaction'))
    status_dict = get_status(paper, user)
    comments = get_comments(paper, user)
    paper_molecules = get_paper_molecules(paper)
    admin_panel = False
    admin_dict = {}
    if current_user.has_role('admin'):
        admin_panel = True
        admin_dict = get_admin_dict(paper)

    reactions_ordered = reactions_in_activity + [r for r in reactions_in_paper if r not in reactions_in_activity]
    reactions_ordered += [r for r in reactions_in_paper if r not in reactions_ordered]
    reactions_ordered += [r for r in reactions if r not in reactions_ordered]

    return render_template('data_submission/submission_main_page.html',
                           paper=paper_data,
                           activity_data=activity_data,
                           seq_data=enzyme_data, seq_button_columns=['edit', 'remove', 'papers'],
                           status=status_dict,
                           seq_table_height='60vh', enzyme_types=enzyme_types, show_header_filters=False, include_owner=True, lock_enz_type='false',
                           reactions=reactions_ordered, enzyme_names=enzyme_names+['Chemical'],
                           doi=paper.doi,
                           comments=comments,
                           paper_molecules=paper_molecules,
                           admin_panel=admin_panel,
                           admin_dict=admin_dict,
                           enzyme_reactions=reactions_in_paper)

@bp.route('/_check_connection', methods=['GET', 'POST'])
def check_connection():
    return jsonify({'status': 'success'})
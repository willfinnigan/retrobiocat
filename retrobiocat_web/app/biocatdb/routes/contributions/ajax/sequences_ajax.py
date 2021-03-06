from retrobiocat_web.app.biocatdb import bp
from flask import request, jsonify, flash
from flask_security import roles_required, current_user
from retrobiocat_web.mongo.models.biocatdb_models import Sequence, Activity, EnzymeType, Paper
from retrobiocat_web.app.app import user_datastore
from distutils.util import strtobool
from retrobiocat_web.app.biocatdb.functions.papers import paper_status, papers_functions
from werkzeug.utils import secure_filename
import os
import pandas as pd
import numpy as np
from distutils.util import strtobool
from retrobiocat_web.app.biocatdb.functions import check_permission
from retrobiocat_web.mongo.functions.sequence_functions import sequence_check
import requests
from Bio import Entrez, SeqIO
Entrez.email = 'william.finnigan@manchester.ac.uk'

INVALID_NAME_CHARS = [".", "(", ")", "'", "/"]

def seqs_of_type(enzyme_type):
    if enzyme_type == 'All':
        sequences = Sequence.objects().distinct('enzyme_name')
        sequences.sort()
    else:
        sequences = Sequence.objects(enzyme_type=enzyme_type).distinct('enzyme_name')
        sequences.sort()

    seq_array = {}
    for seq in sequences:
        seq_array[seq] = seq

    result = {'sequences': seq_array}
    return result

@bp.route('/_sequences_of_same_type', methods=['GET', 'POST'])
def get_sequences_of_same_type():
    enzyme_type = Sequence.objects(enzyme_name=request.form['enzyme_name'])[0].enzyme_type
    result = seqs_of_type(enzyme_type)

    return jsonify(result=result)

@bp.route('/_sequences_of_type', methods=['GET', 'POST'])
def get_sequences_of_type():
    enzyme_type = request.form['enzyme_type']
    result = seqs_of_type(enzyme_type)

    return jsonify(result=result)




@bp.route('/_save_edited_sequence', methods=['GET', 'POST'])
@roles_required('contributor')
def save_edited_sequence():
    original_name = request.form['original_name']
    enzyme_name = request.form['enzyme_name']
    enzyme_type = request.form['enzyme_type']
    sequence = request.form['sequence']
    sequence_unavailable = bool(strtobool(request.form['sequence_unavailable']))
    n_tag = request.form['n_tag']
    c_tag = request.form['c_tag']
    accession = request.form['accession']
    other_identifiers = request.form['other_identifiers']
    pdb = request.form['pdb']
    mutant_of = request.form['mutant_of']
    notes = request.form['notes']
    other_names = request.form['other_names']
    bioinformatics_ignore = bool(strtobool(request.form['bioinformatics_ignore']))

    status = 'success'
    msg = 'Sequence edited'
    issues = []

    seq = Sequence.objects(enzyme_name=original_name)[0]
    user = user_datastore.get_user(current_user.id)

    if not check_permission.check_seq_permissions(current_user.id, seq):
        issues.append('User does not have access to edit this sequence')

    if original_name != enzyme_name:
        success, msg = seq.update_name(enzyme_name)
        if success is False:
            issues.append(msg)

    if seq.enzyme_type != enzyme_type:
        success, msg = seq.update_type(enzyme_type)
        if success is False:
            issues.append(msg)

    if seq.sequence != sequence:
        success, msg = seq.update_sequence(sequence)
        if success is False:
            issues.append(msg)

    seq.sequence_unavailable = sequence_unavailable
    seq.n_tag = n_tag
    seq.c_tag = c_tag
    seq.accession = accession
    seq.other_identifiers = other_identifiers.split(', ')
    seq.pdb = pdb
    seq.notes = notes
    seq.mutant_of = mutant_of
    seq.other_names = other_names.split(', ')
    seq.bioinformatics_ignore = bioinformatics_ignore
    seq.save()

    self_assigned = bool(strtobool(request.form['self_assigned']))
    if self_assigned == True:
        seq.owner = user
    elif self_assigned == False and seq.owner == user:
        seq.owner = None

    update_seq_papers_status(seq.enzyme_name)

    if len(issues) != 0:
        status = 'danger'
        msg = 'Issues updating sequence'

    result = {'status': status,
              'msg': msg,
              'issues': issues}
    return jsonify(result=result)



@bp.route('/_change_sequence_assign', methods=['GET', 'POST'])
@roles_required('contributor')
def change_sequence_assign():
    original_name = request.form['original_name']
    self_assigned = bool(strtobool(request.form['self_assigned']))
    print(self_assigned)

    user = user_datastore.get_user(current_user.id)
    seq = Sequence.objects(enzyme_name=original_name)[0]

    if (seq.owner == user) and (self_assigned is False):
        seq.owner = None
        seq.save()
    elif (seq.owner == None) and (self_assigned == True):
        seq.owner = user
        seq.save()

    result = {'status': 'success',
              'msg': 'Sequence assigned',
              'issues': []}
    return jsonify(result=result)



@bp.route('/_load_sequence_data', methods=['GET', 'POST'])
def load_sequence_data():

    name = request.form['name']

    if name == '':
        return jsonify(result={})

    seq = Sequence.objects(enzyme_name=name).exclude('papers')[0].select_related()

    sequences_same_type = Sequence.objects(enzyme_type=seq.enzyme_type).distinct('enzyme_name')
    sequences_same_type.sort()

    seq_array = {}
    for seq_same_type in sequences_same_type:
        seq_array[seq_same_type] = seq_same_type

    can_edit = False
    self_assigned = False
    other_user = False
    if current_user.is_authenticated:
        user = user_datastore.get_user(current_user.id)
        if check_permission.check_seq_permissions(current_user.id, seq):
            can_edit = True

        if seq.owner == user:
            self_assigned = True
        else:
            if seq.owner != '' and seq.owner is not None:
                other_user = True

    if seq.owner is None:
        owner = ''
    else:
        owner = f"{seq.owner.first_name} {seq.owner.last_name}, {seq.owner.affiliation}"


    other_names = ''
    for i, name in enumerate(seq.other_names):
        other_names += name
        if (len(seq.other_names) > 1) and (i < len(seq.other_names)-1):
            other_names += ', '

    other_identifiers = ''
    for i, ident in enumerate(seq.other_identifiers):
        other_identifiers += ident
        if (len(seq.other_identifiers) > 1) and (i < len(seq.other_identifiers)-1):
            other_identifiers += ', '

    enzyme_type_full = EnzymeType.objects(enzyme_type=seq.enzyme_type)[0].full_name

    if seq.n_tag is None:
        seq.n_tag = ''
    if seq.c_tag is None:
        seq.c_tag = ''
    if seq.pdb is None:
        seq.pdb = ''

    result = {'enzyme_type': seq.enzyme_type,
              'enzyme_name': seq.enzyme_name,
              'sequence': seq.sequence,
              'sequence_unavailable': seq.sequence_unavailable,
              'n_tag': seq.n_tag,
              'c_tag': seq.c_tag,
              'accession': seq.accession,
              'other_identifiers': other_identifiers,
              'pdb': seq.pdb,
              'mutant_of': seq.mutant_of,
              'sequences': seq_array,
              'notes': seq.notes,
              'bioinformatics_ignore': seq.bioinformatics_ignore,
              'can_edit': can_edit,
              'self_assigned': self_assigned,
              'owner_is_another_user': other_user,
              'other_names': other_names,
              'owner': owner,
              'enzyme_type_full': enzyme_type_full}

    return jsonify(result=result)

@bp.route('/_delete_sequence', methods=['GET', 'POST'])
@roles_required('contributor')
def delete_sequence():
    to_delete = request.form['to_delete']

    seq = Sequence.objects(enzyme_name=to_delete)[0]
    acts = Activity.objects(enzyme_name=to_delete)

    status = 'success'
    msg = 'Sequence deleted'
    issues = []

    if len(acts) != 0:
        status = 'danger'
        msg = 'Could not delete'
        papers = []
        for act in acts:
            if act.short_citation not in papers:
                papers.append(act.short_citation)
        for paper in papers:
            issues.append(f"Sequence is recorded in activity data for {paper}")

    mutants = Sequence.objects(mutant_of=to_delete)
    if len(mutants) != 0:
        status = 'danger'
        msg = 'Could not delete'
        for mut in mutants:
            issues.append(f"Sequence is a parent of mutant {mut.enzyme_name}")

    if status == 'success':
        seq.delete()

    result = {'status': status,
              'msg': msg,
              'issues': issues}

    return jsonify(result=result)

@bp.route('/_merge_seq', methods=['GET', 'POST'])
@roles_required('contributor')
def merge_sequences():
    to_merge = request.form['to_merge']
    merge_with = request.form['merge_with']
    status = 'success'
    msg = 'Sequences merged'
    issues = []

    if to_merge != merge_with:
        seq = Sequence.objects(enzyme_name=to_merge)[0]
        seq_merge = Sequence.objects(enzyme_name=merge_with)[0]
        if seq.enzyme_type == seq_merge.enzyme_type:
            for paper in seq.papers:
                seq_merge.papers.append(paper)

            acts = Activity.objects(enzyme_name=to_merge)
            for act in acts:
                act.enzyme_name = seq_merge.enzyme_name
                act.save()
            seq.delete()
            seq_merge.other_names.append(to_merge)
            seq_merge.save()
            update_seq_papers_status(merge_with)
        else:
            status = 'danger'
            msg = 'Could not merge sequences'
            issues.append('Enzyme types must be the same')
    else:
        status = 'danger'
        msg = 'Could not merge sequences'
        issues.append('Cannot merge with self')

    result = {'status': status,
              'msg': msg,
              'issues': issues}

    return jsonify(result=result)

@bp.route('/_load_sequence_papers', methods=['GET', 'POST'])
def load_sequence_papers():
    enzyme_name = request.form['name']
    seq = Sequence.objects(enzyme_name=enzyme_name).select_related()[0]

    papers_list = []
    for paper in seq.papers:
        paper_dict = {}
        paper_dict['_id'] = str(paper.id)
        paper_dict['short_citation'] = paper.short_citation
        paper_dict['doi'] = paper.doi
        paper_dict['title'] = paper.title

        if current_user.is_authenticated:
            if check_permission.check_seq_permissions(current_user.id, seq):
                paper_dict['can_edit'] = "True"
            else:
                paper_dict['can_edit'] = "False"
        else:
            paper_dict['can_edit'] = "False"

        papers_list.append(paper_dict)

    result = {'papers': papers_list}

    return jsonify(result=result)

def update_seq_papers_status(enzyme_name):
    seq = Sequence.objects(enzyme_name=enzyme_name).select_related()[0]
    for paper in seq.papers:
        papers_functions.tag_paper_with_enzyme_types(paper)
        paper_progress_text, paper_progress = paper_status.paper_metadata_status(paper)
        sequence_progress_text, sequence_progress = paper_status.sequences_status(paper)
        activity_progress_text, activity_progress = paper_status.activity_status(paper)
        status, status_colour = paper_status.get_status(paper_progress, sequence_progress, activity_progress, paper)

        paper.status = status
        paper.save()


@bp.route('/_upload_sequence_excel', methods=['GET', 'POST'])
@roles_required('contributor')
def upload_sequence_excel():
    issues = []
    if request.method != 'POST':
        issues.append('Method is not POST')
    else:
        excel_file = request.files['file_seq']
        paper = Paper.objects(id=request.form['paper_id_field'])[0]
        filename = secure_filename(excel_file.filename)
        if filename[-5:] == '.xlsx':
            excel_file.save(filename)
            df = pd.read_excel(filename)
            data_list = process_uploaded_excel(df)
            os.remove(filename)

            save_issues = save_or_add_seqs(data_list, paper)

            if len(save_issues) == 0:
                result = {'status': 'success',
                          'msg': 'Sequences saved and added to paper',
                          'issues': []}
                flash("Sequences saved and added to paper", "success")
            else:
                result = {'status': 'warning',
                          'msg': 'Sequences saved with some issues:',
                          'issues': save_issues}
                flash("Sequences saved with some issues", "warning")
            return jsonify(result=result)
        else:
            issues.append('File does not end in .xlsx')

    result = {'status': 'danger',
              'msg': 'Error processing file',
              'issues': issues}
    return jsonify(result=result)

def process_uploaded_excel(df):
    cols = ['enzyme_type', 'enzyme_name', 'other_names', 'sequence',
            'sequence_unavailable', 'accession', 'structure',
            'mutant_of', 'notes']

    cols_to_keep = [c for c in cols if c in list(df.columns)]
    df = df[cols_to_keep]
    df.replace(np.nan, '', inplace=True)

    data_list = df.to_dict(orient='records')

    # Remove any spaces at end
    for i, data in enumerate(data_list):
        while data_list[i]['enzyme_name'][-1] == ' ':
            print("Removing end space")
            data_list[i]['enzyme_name'] = data_list[i]['enzyme_name'][:-1]


    return data_list

def save_or_add_seqs(data_list, paper):
    # Used by upload excel
    user = user_datastore.get_user(current_user.id)
    issues = []
    enzyme_types = EnzymeType.objects().distinct('enzyme_type')

    for seq_dict in data_list:
        if 'sequence_unavailable' in seq_dict:
            if seq_dict['sequence_unavailable'] == '':
                seq_dict['sequence_unavailable'] = 'False'

        if 'structure' in seq_dict:
            if seq_dict['structure'] == '':
                seq_dict['structure'] = 'False'

        if 'sequence' in seq_dict:
            seq_dict['sequence'] = seq_dict['sequence'].replace('\n', '')
            seq_dict['sequence'] = seq_dict['sequence'].replace(' ', '')

        if seq_dict.get('enzyme_name','') == '':
            issues.append(f"Sequence must have a name")
        else:
            if len(Sequence.objects(enzyme_name=seq_dict['enzyme_name'])) == 0:
                if seq_dict.get('enzyme_type', '') not in enzyme_types:
                    print(f"Enzyme type {seq_dict.get('enzyme_type', '')} does not exist")
                    issues.append(f"Enzyme type {seq_dict.get('enzyme_type', '')} does not exist")

                elif sequence_check(seq_dict.get('sequence','')) == False:
                    print(f"Amino acid sequence for {seq_dict['enzyme_name']} uses incorrect amino acid characters")
                    issues.append(f"Amino acid sequence for {seq_dict['enzyme_name']} uses incorrect amino acid characters")

                else:
                    print('Creating new sequence..')
                    seq = Sequence(enzyme_name=seq_dict['enzyme_name'],
                                   enzyme_type=seq_dict['enzyme_type'],
                                   other_names=seq_dict.get('other_names', '').split(', '),
                                   sequence=seq_dict.get('sequence', ''),
                                   n_tag=seq_dict.get('n_tag', ''),
                                   c_tag=seq_dict.get('c_tag', ''),
                                   sequence_unavailable=strtobool(seq_dict.get('sequence_unavailable','False')),
                                   accession=seq_dict.get('accession', ''),
                                   other_identifiers=seq_dict.get('other_names', '').split(', '),
                                   pdb=seq_dict.get('pdb',''),
                                   mutant_of=seq_dict.get('mutant_of', ''),
                                   notes=seq_dict.get('notes', ''),
                                   papers=[paper],
                                   owner=user)
                    seq.save()

            else:
                seq = Sequence.objects(enzyme_name=seq_dict['enzyme_name'])[0]
                if paper not in seq.papers:
                    seq.papers.append(paper)

                if seq.owner == user or seq.owner is None:
                    seq.owner = user
                    other_names = seq_dict.get('other_names', '').split(', ')
                    seq.other_names.extend(other_names)

                    if (seq.sequence is None or seq.sequence == ''):
                        seq.sequence = seq_dict.get('sequence', '')

                    if strtobool(seq_dict.get('sequence_unavailable','False')) == True:
                        seq.sequence_unavailable = True

                    if (seq.accession is None or seq.accession == ''):
                        seq.accession = seq_dict.get('accession', '')

                    if seq_dict.get('pdb', '') != '':
                        seq.pdb = seq_dict.get('pdb','')

                    if (seq.mutant_of is None or seq.mutant_of == ''):
                        seq.mutant_of = seq_dict.get('mutant_of', '')

                    if (seq.notes is None or seq.notes == ''):
                        seq.notes = seq_dict.get('notes', '')

                else:
                    print('Sequence already exists but owned by another user - added to paper, but no data updated')
                    issues.append('Sequence already exists but owned by another user - added to paper, but no data updated')

                seq.save()

    return issues


def lookup_uniprot(accession):
    url = f"https://www.uniprot.org/uniprot/{accession}.fasta"
    req = requests.get(url)

    if req.status_code in [200]:
        fasta = req.text
        seq = fasta[fasta.find('\n'):]
        seq = seq.replace('\n', '')
    else:
        seq = ''

    return seq


def lookup_ncbi(accession):
    try:
        handle = Entrez.efetch(db="protein", id=accession, rettype="fasta", retmode="text")
        record = SeqIO.read(handle, 'fasta')
        seq = str(record.seq)
    except:
        seq = ''

    return seq




@bp.route('/_get_sequence_from_uniprot',methods=['GET', 'POST'])
def get_sequence_from_uniprot():
    accession = request.form['accession']

    seq = lookup_uniprot(accession)

    if seq != "":
        loaded_from = 'Uniprot'
    else:
        seq = lookup_ncbi(accession)

    if seq != "":
        loaded_from = 'NCBI'
        result = {'status': 'success',
                  'msg': f'Sequence loaded from {loaded_from}',
                  'issues': [],
                  'seq': seq}

    else:
        result = {'status': 'danger',
                  'msg': 'Sequence not found',
                  'issues': [],
                  'seq': seq}

    print(seq)

    return jsonify(result=result)


if __name__ == "__main__":
    accession = 'WP_008741284.1'
    lookup_ncbi(accession)




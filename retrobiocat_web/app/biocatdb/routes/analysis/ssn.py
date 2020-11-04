from retrobiocat_web.app.biocatdb import bp
from flask import render_template, flash, redirect, url_for, request, jsonify, session, current_app
from flask_security import roles_required, current_user
from retrobiocat_web.mongo.models.biocatdb_models import Paper, Activity, Sequence, Molecule, Tag, EnzymeType, SSN_record
from retrobiocat_web.analysis import embl_restfull, all_by_all_blast, make_ssn
from rq.registry import StartedJobRegistry
import datetime
import mongoengine as db
from rq.job import Job
from rq import get_current_job
from retrobiocat_web.analysis.make_ssn import SSN, SSN_Visualiser
from retrobiocat_web.app.biocatdb.forms import SSN_Form
import json

@bp.route('/ssn_page/<task_id>/', methods=['GET'])
def ssn_page(task_id):
    task = current_app.network_queue.fetch_job(task_id)
    result = task.result
    node_one = result['nodes'][0]
    start_pos = {'x': node_one['x'], 'y': node_one['y']}

    return render_template('ssn/ssn.html',
                           nodes=result['nodes'],
                           edges=result['edges'],
                           alignment_score=result['alignment_score'],
                           start_pos=start_pos)

def task_get_ssn(enzyme_type, score, include_mutants, only_biocatdb):
    job = get_current_job()
    job.meta['progress'] = 'started'
    job.save_meta()

    ssn = SSN(enzyme_type)
    ssn.load(include_mutants=include_mutants, only_biocatdb=only_biocatdb)

    if str(score) in ssn.db_object.pos_at_alignment_score:
        precalc_pos = ssn.db_object.pos_at_alignment_score[str(score)]
    else:
        precalc_pos = None

    vis = SSN_Visualiser(enzyme_type, log_level=1)
    nodes, edges = vis.visualise(ssn, score, precalc_pos=precalc_pos)



    result = {'nodes': nodes,
              'edges': edges,
              'alignment_score': score}

    return result

@bp.route("/ssn_status/<task_id>", methods=["GET"])
def ssn_status(task_id):
    task = current_app.network_queue.fetch_job(task_id)
    progress = 'queuing'
    if 'progress' in task.meta:
        progress = task.meta['progress']

    if task:
        response_object = {
            "status": "success",
            "data": {
                "task_id": task.get_id(),
                "task_status": task.get_status(),
                "task_progress": progress
            },
        }
    else:
        response_object = {"status": "error"}

    return jsonify(response_object), 202

@bp.route('/ssn_form', methods=['GET', 'POST'])
@roles_required('experimental')
def ssn_form():
    form = SSN_Form()
    form.set_choices()

    task_id = ''

    if 'ssn_task_id' in session:
        old_task_id = session['ssn_task_id']
    else:
        old_task_id = None

    if form.validate_on_submit() == True:
        enzyme_type = form.data['enzyme_type']
        min_score = form.data['alignment_score']
        include_mutants = form.data['include_mutants']
        only_biocatdb = form.data['only_biocatdb']
        task = current_app.network_queue.enqueue(task_get_ssn, enzyme_type, min_score, include_mutants, only_biocatdb)

        if old_task_id != None:
            try:
                old_job = Job.fetch(old_task_id, connection=current_app.redis)
                old_job.delete()
            except:
                pass

        task_id = task.get_id()
        session['ssn_task_id'] = task_id

    return render_template('ssn/ssn_form.html', form=form, task_id=task_id)

@bp.route("/_ssn_object_status", methods=["POST"])
def ssn_object_status():
    enzyme_type = request.form['enzyme_type']
    enzyme_type_obj = EnzymeType.objects(enzyme_type=enzyme_type)[0]
    ssn_obj = SSN_record.objects(enzyme_type=enzyme_type_obj)[0]

    alignment_cluster_data = []
    max_clusters = 0
    max_alignment = 0
    min_alignment = 300
    if ssn_obj.num_at_alignment_score is not None:
        for score_string, num_clusters in ssn_obj.num_at_alignment_score.items():
            score = int(score_string)
            data = {'alignment_score': score, 'num_clusters': int(num_clusters)}
            alignment_cluster_data.append(data)
            if score > max_alignment:
                max_alignment = score
            if score < min_alignment:
                min_alignment = score
            if num_clusters > max_clusters:
                max_clusters = num_clusters

    alignment_identity_data = []
    if ssn_obj.identity_at_alignment_score is not None:
        for score_string, identity_data in ssn_obj.identity_at_alignment_score.items():
            score = int(score_string)
            if score > max_alignment:
                max_alignment = score
            data = {'alignment_score': score,
                    'i_avg': identity_data[0],
                    'i_stdev': identity_data[1]}
            alignment_identity_data.append(data)

    result = {'status': ssn_obj.status,
              'alignment_cluster_data': alignment_cluster_data,
              'alignment_identity_data': alignment_identity_data,
              'max_clusters': max_clusters + 1,
              'max_alignment': max_alignment + 5,
              'min_alignment': min_alignment - 5}
    return jsonify(result=result)




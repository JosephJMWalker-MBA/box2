<?php
declare(strict_types=1);

const TOP5_VERSION = '2026-10-13-organic-compilation';
const TOP5_PLATFORMS = ['tiktok'=>'TikTok','instagram'=>'Instagram Reels','facebook'=>'Facebook Reels','youtube'=>'YouTube Shorts'];

function timecode_ms(string $value): int
{
    if (!preg_match('/^(\d{1,2}):([0-5]\d):([0-5]\d)(?:\.(\d{1,3}))?$/D',$value,$m)) throw new InvalidArgumentException('Use HH:MM:SS or HH:MM:SS.mmm timecodes.');
    return ((int)$m[1]*3600+(int)$m[2]*60+(int)$m[3])*1000+(int)str_pad($m[4]??'',3,'0');
}

function editorial_candidate(string $id): array
{
    $candidate=query('SELECT * FROM editorial_candidates WHERE id=?',[$id])->fetch();
    if (!$candidate) throw new InvalidArgumentException('Candidate not found.');
    return $candidate;
}

function recorded_clip_booking(string $id): array
{
    $booking=booking_record($id);
    if ($booking['status']!=='performed' || $booking['consent_level']!=='clip_eligible'
        || !$booking['livestream_allowed'] || !$booking['archive_allowed'] || !$booking['clips_allowed']) {
        throw new InvalidArgumentException('Only performed, expressly recorded/clip-permitted material can enter this ledger. No private or live-only material.');
    }
    return $booking;
}

function create_editorial_candidate(array $data): string
{
    require_admin();
    $booking=recorded_clip_booking(field($data,'booking_id',24,true));
    $week=field($data,'week_date',10,true);show_date($week);
    $source=field($data,'source_reference',300,true);
    $duration=timecode_ms(field($data,'source_duration',20,true));
    $in=timecode_ms(field($data,'in_time',20,true));$out=timecode_ms(field($data,'out_time',20,true));
    if ($in<0 || $out<=$in || $out>$duration) throw new InvalidArgumentException('Timecodes must lie inside the actual source recording.');
    $origin=field($data,'origin',30,true);
    if (!in_array($origin,['performer_original','writer_submission','unclear'],true)) throw new InvalidArgumentException('Declare the material origin.');
    $writer=field($data,'writer_id',24);
    if ($origin==='writer_submission' && (!$writer || !query('SELECT 1 FROM writer_submissions WHERE id=?',[$writer])->fetchColumn())) throw new InvalidArgumentException('Link the underlying writer submission.');
    if ($origin!=='writer_submission' && $writer!=='') throw new InvalidArgumentException('Writer reference and origin must agree.');
    $id=bin2hex(random_bytes(12));
    query('INSERT INTO editorial_candidates(id,booking_id,week_date,source_reference,source_duration_ms,in_ms,out_ms,title,note,source_verified,layers_cleared,origin,writer_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        [$id,$booking['id'],$week,$source,$duration,$in,$out,field($data,'title',120,true),field($data,'note',1000),flag($data,'source_verified'),flag($data,'layers_cleared'),$origin,$writer?:null,utc()]);
    audit('editorial_candidate_created',$id);return $id;
}

function editorial_link(string $id,string $role,string $purpose='grant'): string
{
    if ($purpose==='grant') require_admin();
    $candidate=editorial_candidate($id);
    if (!in_array($role,['performer','writer'],true) || !in_array($purpose,['grant','withdraw'],true)
        || ($role==='writer' && !$candidate['writer_id'])) throw new InvalidArgumentException('Invalid rights role.');
    $token=bin2hex(random_bytes(32));
    query('INSERT INTO editorial_tokens(token_hash,candidate_id,role,purpose,expires_at,version) VALUES (?,?,?,?,?,?)',
        [hash('sha256',$token),$id,$role,$purpose,utc((new DateTimeImmutable())->modify($purpose==='grant'?'+7 days':'+30 days')),TOP5_VERSION]);
    $signature=hash_hmac('sha256','top5:'.$purpose.':'.$token,config()['secret']);
    return url('/release?'.http_build_query(['purpose'=>$purpose,'token'=>$token,'signature'=>$signature]));
}

function editorial_authorization(array $data): array
{
    $purpose=field($data,'purpose',10,true);$token=field($data,'token',64,true);$sig=field($data,'signature',64,true);
    if (!in_array($purpose,['grant','withdraw'],true) || !preg_match('/^[a-f0-9]{64}$/D',$token)
        || !hash_equals(hash_hmac('sha256','top5:'.$purpose.':'.$token,config()['secret']),$sig)) throw new InvalidArgumentException('Invalid release link.');
    $record=query('SELECT * FROM editorial_tokens WHERE token_hash=? AND purpose=? AND used_at IS NULL AND expires_at>?',
        [hash('sha256',$token),$purpose,utc()])->fetch();
    if (!$record || $record['version']!==TOP5_VERSION) throw new InvalidArgumentException('Release link expired, was used, or belongs to an older permission scope.');
    return $record;
}

function apply_editorial_release(array $data): array
{
    return transaction(function () use ($data): array {
        $authorization=editorial_authorization($data);$id=$authorization['candidate_id'];$role=$authorization['role'];
        $candidate=editorial_candidate($id);
        if ($authorization['purpose']==='withdraw') {
            query('UPDATE editorial_grants SET revoked_at=? WHERE candidate_id=? AND role=?',[utc(),$id,$role]);
            query("UPDATE editorial_candidates SET review_status='withdrawn' WHERE id=?",[$id]);
            query('UPDATE weekly_posts SET removal_requested=1 WHERE week_date=?',[$candidate['week_date']]);
            if (!query('SELECT 1 FROM weekly_posts WHERE week_date=?',[$candidate['week_date']])->fetchColumn()) {
                query('DELETE FROM weekly_selections WHERE candidate_id=?',[$id]);
                query("UPDATE weekly_reels SET review_status='draft',master_reference='' WHERE week_date=?",[$candidate['week_date']]);
            }
            $result=['withdrawn'=>true];
        } else {
            if (query('SELECT 1 FROM weekly_posts WHERE week_date=?',[$candidate['week_date']])->fetchColumn()) throw new InvalidArgumentException('This week already has posted material; contact the host for changes.');
            if (!flag($data,'scope_acknowledged')) throw new InvalidArgumentException('Acknowledge this specific organic weekly compilation scope.');
            $credit=flag($data,'credit_allowed');
            query('INSERT INTO editorial_grants(candidate_id,role,tiktok,instagram,facebook,youtube,face_voice,credit_allowed,public_credit,public_handle,version,consented_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(candidate_id,role) DO UPDATE SET tiktok=excluded.tiktok,instagram=excluded.instagram,facebook=excluded.facebook,youtube=excluded.youtube,face_voice=excluded.face_voice,credit_allowed=excluded.credit_allowed,public_credit=excluded.public_credit,public_handle=excluded.public_handle,version=excluded.version,consented_at=excluded.consented_at,revoked_at=NULL',
                [$id,$role,flag($data,'tiktok'),flag($data,'instagram'),flag($data,'facebook'),flag($data,'youtube'),flag($data,'face_voice'),$credit,
                 $credit?field($data,'public_credit',100,true):'', $credit?field($data,'public_handle',100):'',TOP5_VERSION,utc()]);
            query('DELETE FROM weekly_selections WHERE candidate_id=?',[$id]);
            query("UPDATE editorial_candidates SET review_status='candidate' WHERE id=?",[$id]);
            query("UPDATE weekly_reels SET review_status='draft',master_reference='' WHERE week_date=?",[$candidate['week_date']]);
            $result=['withdrawal'=>editorial_link($id,$role,'withdraw')];
        }
        query('UPDATE editorial_tokens SET used_at=? WHERE token_hash=?',[utc(),$authorization['token_hash']]);
        audit('editorial_'.$authorization['purpose'].'_'.$role,$id);
        return $result;
    });
}

function editorial_eligible(array $candidate): void
{
    recorded_clip_booking($candidate['booking_id']);
    if (!$candidate['source_verified'] || !$candidate['layers_cleared'] || $candidate['origin']==='unclear'
        || in_array($candidate['review_status'],['withdrawn','rejected'],true)) throw new InvalidArgumentException('Source, layer rights and material origin need review.');
    $roles=['performer'];
    if ($candidate['origin']==='writer_submission') {
        $writer=query('SELECT * FROM writer_submissions WHERE id=?',[$candidate['writer_id']])->fetch();
        if (!$writer || !$writer['perform_allowed'] || !$writer['publish_allowed'] || $writer['status']==='withdrawn') throw new InvalidArgumentException('Underlying writer performance and publication permission are required.');
        $roles[]='writer';
    }
    foreach ($roles as $role) {
        $grant=query('SELECT * FROM editorial_grants WHERE candidate_id=? AND role=?',[$candidate['id'],$role])->fetch();
        if (!$grant || $grant['revoked_at'] || $grant['version']!==TOP5_VERSION || ($role==='performer' && !$grant['face_voice'])) throw new InvalidArgumentException('A current clip-specific performer/writer release is missing.');
        foreach (TOP5_PLATFORMS as $platform=>$label) if (!$grant[$platform]) throw new InvalidArgumentException('Every moment needs explicit permission for all four organic destinations.');
    }
}

function review_editorial_candidate(string $id,string $status): void
{
    require_admin();
    if (!in_array($status,['approved','rejected'],true)) throw new InvalidArgumentException('Invalid review status.');
    transaction(function () use ($id,$status): void {
        $candidate=editorial_candidate($id);
        if (query('SELECT 1 FROM weekly_posts WHERE week_date=?',[$candidate['week_date']])->fetchColumn()) throw new InvalidArgumentException('Posted history is retained; use removal/withdrawal workflow.');
        if ($status==='approved') editorial_eligible($candidate);
        else {
            query('DELETE FROM weekly_selections WHERE candidate_id=?',[$id]);
            query("UPDATE weekly_reels SET review_status='draft',master_reference='' WHERE week_date=?",[$candidate['week_date']]);
        }
        query('UPDATE editorial_candidates SET review_status=? WHERE id=?',[$status,$id]);
        audit('editorial_review_'.$status,$id);
    });
}

function select_top5(string $id,int $position): void
{
    require_admin();
    if ($position<1 || $position>5) throw new InvalidArgumentException('Select at most five joke moments, positions 1–5.');
    transaction(function () use ($id,$position): void {
        $candidate=editorial_candidate($id);editorial_eligible($candidate);
        if ($candidate['review_status']!=='approved') throw new InvalidArgumentException('Approve rights before selecting.');
        if (query('SELECT 1 FROM weekly_posts WHERE week_date=?',[$candidate['week_date']])->fetchColumn()) throw new InvalidArgumentException('This week has posted URLs; selections are frozen.');
        query('INSERT OR IGNORE INTO weekly_reels(week_date,created_at) VALUES (?,?)',[$candidate['week_date'],utc()]);
        if (query('SELECT 1 FROM weekly_selections WHERE week_date=? AND position=? AND candidate_id!=?',[$candidate['week_date'],$position,$id])->fetchColumn()) throw new InvalidArgumentException('This position is occupied. Unselect it first.');
        query('DELETE FROM weekly_selections WHERE candidate_id=?',[$id]);
        query('INSERT INTO weekly_selections(week_date,candidate_id,position) VALUES (?,?,?)',[$candidate['week_date'],$id,$position]);
        query("UPDATE weekly_reels SET review_status='draft',master_reference='' WHERE week_date=?",[$candidate['week_date']]);audit('top5_selected',$id);
    });
}

function validate_top5_week(string $week): array
{
    show_date($week);
    $entries=query('SELECT c.* FROM weekly_selections s JOIN editorial_candidates c ON c.id=s.candidate_id WHERE s.week_date=? ORDER BY s.position',[$week])->fetchAll();
    if (!$entries || count($entries)>5) throw new InvalidArgumentException('Choose one to five authorized moments; do not fill missing rights.');
    foreach ($entries as $candidate) {editorial_eligible($candidate);if ($candidate['review_status']!=='approved') throw new InvalidArgumentException('Every selected moment must remain approved.');}
    return $entries;
}

function unselect_top5(string $id): void
{
    require_admin();
    transaction(function () use ($id): void {
        $candidate=editorial_candidate($id);
        if (query('SELECT 1 FROM weekly_posts WHERE week_date=?',[$candidate['week_date']])->fetchColumn()) throw new InvalidArgumentException('Posted selections stay in the removal/audit history.');
        query('DELETE FROM weekly_selections WHERE candidate_id=?',[$id]);
        query("UPDATE weekly_reels SET review_status='draft',master_reference='' WHERE week_date=?",[$candidate['week_date']]);
        audit('top5_unselected',$id);
    });
}

function edited_top5(string $week,array $data): void
{
    require_admin();
    transaction(function () use ($week,$data): void {
        validate_top5_week($week);
        if (!flag($data,'master_rights_reviewed') || !flag($data,'preview_reviewed')) throw new InvalidArgumentException('Review all master layers and performer preview/objection handling.');
        if (query('SELECT 1 FROM weekly_posts WHERE week_date=?',[$week])->fetchColumn()) throw new InvalidArgumentException('Cannot replace a posted master in this ledger.');
        query("UPDATE weekly_reels SET master_reference=?,review_status='edited' WHERE week_date=?",[field($data,'master_reference',300,true),$week]);audit('top5_edited',$week);
    });
}

function record_top5_post(string $week,string $platform,string $url): void
{
    require_admin();
    $hosts=['tiktok'=>['tiktok.com','www.tiktok.com','vm.tiktok.com'],'instagram'=>['instagram.com','www.instagram.com'],
        'facebook'=>['facebook.com','www.facebook.com'],'youtube'=>['youtube.com','www.youtube.com','youtu.be']];
    $parts=parse_url($url);
    if (!isset($hosts[$platform]) || strlen($url)>2048 || !filter_var($url,FILTER_VALIDATE_URL)
        || ($parts['scheme']??'')!=='https' || isset($parts['user']) || isset($parts['pass']) || isset($parts['port'])
        || !in_array(strtolower($parts['host']??''),$hosts[$platform],true) || trim($parts['path']??'','/')==='') throw new InvalidArgumentException('Record an HTTPS post URL on the chosen platform.');
    transaction(function () use ($week,$platform,$url): void {
        validate_top5_week($week);
        $reel=query('SELECT * FROM weekly_reels WHERE week_date=?',[$week])->fetch();
        if (!$reel || !in_array($reel['review_status'],['edited','published'],true) || $reel['master_reference']==='') throw new InvalidArgumentException('Finish the manually reviewed master before recording a posted URL.');
        query('INSERT INTO weekly_posts(week_date,platform,url,recorded_at) VALUES (?,?,?,?) ON CONFLICT(week_date,platform) DO UPDATE SET url=excluded.url,recorded_at=excluded.recorded_at',[$week,$platform,$url,utc()]);
        query("UPDATE weekly_reels SET review_status='published' WHERE week_date=?",[$week]);audit('top5_post_url_recorded_'.$platform,$week);
    });
}

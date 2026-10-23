<?php
// Post-install configuration of Moodle (Demo/PoC), run on every pod start by
// the init container `configure` (after init.sh installed or upgraded the
// database). Idempotent: it creates what is missing and re-applies the
// settings, so a fresh rollout needs no manual step. Input: /setup/setup.json
// (chart values, ConfigMap moodle-setup), MOODLE_DEMO_PASSWORD (Secret, optional).
//
//   - site defaults: language, time zone, start page, no registration wizard,
//     no user tours
//   - LTI 1.3 tool "DHBW AppStore" with a fixed client id (the AppStore's
//     LTI13_CLIENT_ID); the deployment id is Moodle's id of the tool
//   - example course with an LTI activity that launches the AppStore
//   - demo users (teacher/students) when a password is given
define('CLI_SCRIPT', true);
require('/var/www/html/config.php');
require_once($CFG->libdir . '/clilib.php');
require_once($CFG->libdir . '/enrollib.php');
require_once($CFG->dirroot . '/user/lib.php');
require_once($CFG->dirroot . '/course/lib.php');
require_once($CFG->dirroot . '/mod/lti/locallib.php');

// No mail from here (enrolment welcome messages): the pod has no mail transport.
$CFG->noemailever = true;

$setup = json_decode((string) file_get_contents(getenv('MOODLE_SETUP_JSON') ?: '/setup/setup.json'), true) ?: [];
$say = function (string $m) { echo "configure: $m\n"; };
$failures = 0;
$step = function (string $name, callable $fn) use ($say, &$failures) {
    try {
        $fn();
    } catch (Throwable $e) {
        $failures++;
        $say("FAILED $name: " . get_class($e) . ': ' . $e->getMessage() . ' ' . ($e->debuginfo ?? ''));
    }
};

\core\session\manager::set_user(get_admin());

// --- Site defaults ---------------------------------------------------------
$step('site', function () use ($setup, $say, $CFG) {
    $s = $setup['site'] ?? [];
    $lang = $s['lang'] ?? 'en';
    if ($lang !== 'en' && !array_key_exists($lang, get_string_manager()->get_list_of_translations(true))) {
        // The language pack comes from download.moodle.org; an unreleased
        // branch may have none: stay on English then.
        try {
            $controller = new \tool_langimport\controller();
            $controller->install_languagepacks($lang);
            get_string_manager()->reset_caches();
        } catch (Throwable $e) {
            $say("language pack $lang not installed: " . $e->getMessage());
        }
    }
    if (array_key_exists($lang, get_string_manager()->get_list_of_translations(true))) {
        set_config('lang', $lang);
    } else {
        $say("language $lang unavailable, keeping the site language");
    }
    set_config('timezone', $s['timezone'] ?? 'Europe/Berlin');
    set_config('country', $s['country'] ?? 'DE');
    // 0 = site home, 1 = dashboard, 3 = my courses.
    set_config('defaulthomepage', (int) ($s['defaultHomePage'] ?? 3));
    // The "register your site" wizard that an admin gets after the first login.
    set_config('registrationpending', 0);
    set_config('site_is_public', 0);
    // User tours (the pop-up guides at the first visit of each page).
    if (!empty($s['disableTours'] ?? true)) {
        $GLOBALS['DB']->set_field('tool_usertours_tours', 'enabled', 0);
    }
    $say('site settings applied');
});

// --- LTI 1.3 tool ----------------------------------------------------------
$typeid = null;
$step('lti', function () use ($setup, $say, &$typeid) {
    global $DB, $CFG;
    $l = $setup['lti'] ?? [];
    if (empty($l['appstoreHost']) || empty($l['clientId'])) {
        $say('lti: no appstoreHost/clientId configured, skipped');
        return;
    }
    $name = $l['toolName'] ?? 'DHBW AppStore';
    $base = 'https://' . $l['appstoreHost'] . '/api/lti13';
    $type = $DB->get_record('lti_types', ['name' => $name]);
    if (!$type) {
        $t = new stdClass();
        $t->state = LTI_TOOL_STATE_CONFIGURED;
        $t->name = $name;
        $t->ltiversion = LTI_VERSION_1P3;
        $c = new stdClass();
        $c->lti_typename = $name;
        $c->lti_description = 'DHBW AppStore (Demo/PoC)';
        $c->lti_toolurl = "$base/launch";
        $c->lti_ltiversion = LTI_VERSION_1P3;
        $c->lti_clientid = $l['clientId'];
        $c->lti_keytype = LTI_JWK_KEYSET;
        $c->lti_publickeyset = "$base/jwks";
        $c->lti_initiatelogin = "$base/login";
        $c->lti_redirectionuris = "$base/launch";
        $c->lti_coursevisible = LTI_COURSEVISIBLE_ACTIVITYCHOOSER;
        $c->lti_launchcontainer = LTI_LAUNCH_CONTAINER_WINDOW;
        $c->lti_sendname = LTI_SETTING_ALWAYS;
        $c->lti_sendemailaddr = LTI_SETTING_ALWAYS;
        $c->lti_acceptgrades = LTI_SETTING_NEVER;
        $c->lti_forcessl = 1;
        $id = lti_add_type($t, $c);
        $type = $DB->get_record('lti_types', ['id' => $id], '*', MUST_EXIST);
        $say("lti: tool '$name' created (id $id)");
    }
    if ($type->clientid !== $l['clientId']) {
        $DB->set_field('lti_types', 'clientid', $l['clientId'], ['id' => $type->id]);
        $say('lti: client id set to the configured one');
    }
    if ($type->state != LTI_TOOL_STATE_CONFIGURED) {
        $DB->set_field('lti_types', 'state', LTI_TOOL_STATE_CONFIGURED, ['id' => $type->id]);
    }
    // The deployment id Moodle sends is the id of the tool; the AppStore expects the configured one.
    if (!empty($l['deploymentId']) && (string) $type->id !== (string) $l['deploymentId']) {
        $say("lti: WARNING deployment id of the tool is {$type->id}, the AppStore expects {$l['deploymentId']}");
    }
    $typeid = $type->id;
    $say("lti: tool '$name' ready (client id {$l['clientId']}, deployment id {$type->id})");
});

// --- Demo users ------------------------------------------------------------
$users = [];
$step('users', function () use ($setup, $say, &$users) {
    global $DB, $CFG;
    $pw = (string) getenv('MOODLE_DEMO_PASSWORD');
    $lang = get_config('core', 'lang') ?: 'en';
    foreach (($setup['demoUsers'] ?? []) as $d) {
        if ($pw === '') {
            $say('users: no demo password (Secret moodle-demo), demo users skipped');
            return;
        }
        $u = $DB->get_record('user', ['username' => $d['username'], 'mnethostid' => $CFG->mnet_localhost_id, 'deleted' => 0]);
        if (!$u) {
            $n = (object) [
                'username' => $d['username'], 'password' => $pw, 'firstname' => $d['firstName'], 'lastname' => $d['lastName'],
                'email' => $d['email'], 'auth' => 'manual', 'confirmed' => 1, 'mnethostid' => $CFG->mnet_localhost_id, 'lang' => $lang,
            ];
            $uid = user_create_user($n, true, false);
            $u = $DB->get_record('user', ['id' => $uid], '*', MUST_EXIST);
            $say("users: {$d['username']} created");
        }
        $users[] = [$u, $d['role'] ?? 'student'];
    }
});

// --- Example course with an LTI activity -----------------------------------
$step('course', function () use ($setup, $say, &$typeid, &$users) {
    global $DB, $CFG;
    $cs = $setup['course'] ?? [];
    if (empty($cs['shortName']) || $typeid === null) {
        $say('course: not configured or no LTI tool, skipped');
        return;
    }
    $c = $DB->get_record('course', ['shortname' => $cs['shortName']]);
    if (!$c) {
        $c = create_course((object) [
            'fullname' => $cs['fullName'], 'shortname' => $cs['shortName'],
            'category' => $DB->get_field_select('course_categories', 'MIN(id)', '1=1'),
            'visible' => 1, 'format' => 'topics', 'numsections' => 1,
        ]);
        $say("course: '{$cs['fullName']}' created");
    }
    $manual = enrol_get_plugin('manual');
    $inst = $DB->get_record('enrol', ['courseid' => $c->id, 'enrol' => 'manual']);
    if (!$inst) {
        $manual->add_instance($c);
        $inst = $DB->get_record('enrol', ['courseid' => $c->id, 'enrol' => 'manual'], '*', MUST_EXIST);
    }
    $roles = ['teacher' => 'editingteacher', 'student' => 'student'];
    $enrol = [[get_admin(), 'editingteacher']];
    foreach ($users as [$u, $role]) {
        $enrol[] = [$u, $roles[$role] ?? 'student'];
    }
    foreach ($enrol as [$u, $short]) {
        $roleid = $DB->get_field('role', 'id', ['shortname' => $short], MUST_EXIST);
        if (!is_enrolled(context_course::instance($c->id), $u->id)) {
            $manual->enrol_user($inst, $u->id, $roleid);
        }
    }
    $actname = $cs['activityName'] ?? 'AppStore';
    if (!$DB->record_exists('lti', ['course' => $c->id, 'name' => $actname])) {
        $m = new stdClass();
        $m->modulename = 'lti';
        $m->module = $DB->get_field('modules', 'id', ['name' => 'lti']);
        $m->course = $c->id;
        $m->section = 1;
        $m->visible = 1;
        $m->name = $actname;
        $m->typeid = $typeid;
        $m->toolurl = '';
        $m->securetoolurl = '';
        $m->launchcontainer = LTI_LAUNCH_CONTAINER_WINDOW;
        $m->instructorchoicesendname = 1;
        $m->instructorchoicesendemailaddr = 1;
        $m->instructorchoiceacceptgrades = 0;
        $m->instructorchoiceallowroster = null;
        $m->instructorchoiceallowsetting = null;
        $m->showdescriptionlaunch = 0;
        $m->introeditor = ['text' => 'Demo/PoC: Klick-Launch in den DHBW AppStore.', 'format' => FORMAT_HTML, 'itemid' => 0];
        $m->intro = 'Demo/PoC: Klick-Launch in den DHBW AppStore.';
        $m->introformat = FORMAT_HTML;
        $m->cmidnumber = '';
        $m->groupmode = 0;
        $m->groupingid = 0;
        $m->visibleoncoursepage = 1;
        add_moduleinfo($m, $c);
        $say("course: activity '$actname' added");
    }
    $say("course: '{$cs['fullName']}' ready (id {$c->id})");
});

// A failed step must not keep Moodle itself from starting; the log says what is missing.
$say($failures ? "done with $failures failed step(s)" : 'done');
exit(0);

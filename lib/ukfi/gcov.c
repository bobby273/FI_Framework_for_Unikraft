#include<uk/config.h>
#if CONFIG_LIBUKGCOV

#include <uk/gcov.h>
#include<uk/init.h>
#include<uk/print.h>
#include <uk/essentials.h>
#include <uk/sched.h>
#include <uk/pm.h>
#include <uk/arch/time.h>
#include <uk/libparam.h>

static unsigned gcov_after_ms = CONFIG_LIBUKFI_GCOV_AFTER_MS;

UK_LIBPARAM_PARAM(gcov_after_ms, uint, "Time in milliseconds after which to dump gcov info");

#if CONFIG_LIBUKGCOV_OUTPUT_BINARY_FILE
static const char *output_file = CONFIG_LIBUKGCOV_OUTPUT_BINARY_FILENAME;
#else
static const char *output_file = "<console o memoria>";
#endif

//last thing added
int uk_boot_shutdown_req(enum uk_pm_shutdown_op target);


static void __noreturn thread_fno(void) {
    int rc;
    uk_sched_thread_sleep(ukarch_time_msec_to_nsec(gcov_after_ms));
    rc = uk_boot_shutdown_req(UK_PM_SHUTDOWN_OP_SYSHALT);
    if(rc < 0){
        uk_pr_err("Error requesting shutdown\n");
    }else if(rc ==1){
        uk_pr_info("Shutdown has already started\n");
    }else if(rc==0){
        uk_pr_info("Shutdown requested successfully\n");
    }
    uk_sched_thread_exit();

}

static int uk_fi_gcov_init(struct uk_init_ctx *ctx __unused){
    struct uk_thread *thread;

    if(gcov_after_ms == 0) {
        uk_pr_info("gcov profiling disabled\n");
        return 0;
    }
    thread = uk_sched_thread_create_fn0(uk_sched_current(),
					     thread_fno,
					     0,
					     0,
					     false,
					     false,
					     "profiling gcov thread",
					     NULL,
					     NULL);

    if(thread == NULL){
        uk_pr_err("Error creating gcov profiling thread\n");
    }
    
    return 0;
}


//we use term function because the last component initialized is the first to terminate.
//we need the last component to terminate to be vfscore because of the file writing. 
static void uk_fi_gcov_term(struct uk_term_ctx *ctx __unused){
    int rc;
    uk_pr_info("Dumping gcov info into %s\n", output_file);
    rc = ukgcov_dump_info();
    if(rc < 0){
        uk_pr_err("Error dumping gcov info\n");
    }else{
        uk_pr_info("Successfully dumped gcov info\n");
    }

}

uk_late_initcall(uk_fi_gcov_init, uk_fi_gcov_term);

//creo thread
//dorme N millisecondi
//uk_boot_shutdown_req(UK_PM_SHUTDOWN_OP_SYSHALT)
//thread di boot bloccato dalla barriera -> exit
//term
//uk_pm_shutdown() ->halt e QEMU esce

#endif
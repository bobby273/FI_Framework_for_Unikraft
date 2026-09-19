#include <uk/fi.h>
#include <uk/libparam.h>
#include <uk/print.h>
#include <uk/config.h>
#include <uk/init.h>
#include <uk/assert.h>
#include <string.h>

static const char *fi_site = CONFIG_LIBUKFI_FI_SITE;
static int fi_nop = CONFIG_LIBUKFI_FI_NOP;
static int fi_prob = CONFIG_LIBUKFI_FI_PROB;
static int fi_period = CONFIG_LIBUKFI_FI_PERIOD;
static int fi_fault = CONFIG_LIBUKFI_FI_FAULT;
static __u32 fi_seed = CONFIG_LIBUKFI_FI_SEED;

UK_LIBPARAM_PARAM(fi_site, charp,"fault injection site");
UK_LIBPARAM_PARAM(fi_nop, int,"Fire the fault on the n-th invocation of the operation");
UK_LIBPARAM_PARAM(fi_prob, int,"Probability of triggering the fault");
UK_LIBPARAM_PARAM(fi_period, int,"Periodicity of the fault injection");
UK_LIBPARAM_PARAM(fi_seed, __u32,"Random seed for fault injection");

static int uk_fi_init(){
    struct uk_fi_site *itr;
    uk_fi_foreach(itr, uk_fitab_start, uk_fitab_end){
        if(!strcmp("", fi_site) && !strcmp(itr->site, fi_site)){
            if(fi_fault >4 || fi_fault < 0){
                itr->armed = UK_FI_DISARMED;
            }else{
                itr->armed = UK_FI_ARMED;
                itr->inv = 0;
                if(fi_nop <= 0)
                    fi_nop = 1; //default value
                if(fi_prob<0 || fi_prob>100000)
                    fi_prob = 100000; //default value                
                if(fi_period < 0)
                    fi_period = 0; //default value
                if(fi_seed == 0)
                    fi_seed = 1; //default value
                    
                itr->trigger.period = fi_period;
                itr->trigger.prob_on_100000 = fi_prob;
                itr->trigger.n_invocations = fi_nop;
                itr->trigger.prob_on_100000 = fi_prob;
                itr->trigger.period = fi_period;
                itr->faulttype = fi_fault;
            }
        }
        uk_pr_info("Fault injection site: %s:%d, armed=%d, inv=%lu, trigger.n_invocations=%d\n",
            itr->file, itr->line, itr->armed, itr->inv, itr->trigger.n_invocations);
    }
    return 0;

}

uk_early_initcall(uk_fi_init, 0x0);
//the second parameter is 0x0 because NULL expands to (void*)0 and the function crashes seeing the parenthesis character.
//0x0 expands to uk_inittab9_uk_fi_init_0x0, which is a valid identifier and doesn't cause any issues.

int _uk_fi_hit(struct uk_fi_site *site){
    switch(site->faulttype){
        case UK_FI_FAULT_CRASH:
            //crashes and doesn't return anything, so we don't need to return a value here
            UK_CRASH("Crash fault injected at %s:%d\n", site->file, site->line);
            uk_pr_crit("Crash fault injected at %s:%d\n", site->file, site->line);
            break;
        case UK_FI_FAULT_HANG:
            //hangs and doesn't return anything, so we don't need to return a value here
            uk_pr_crit("Hang fault injected at %s:%d\n", site->file, site->line);
            while(1);
            break;
        case UK_FI_FAULT_ERROR:
            uk_pr_crit("Error fault injected at %s:%d\n", site->file, site->line);
            return 1; //returning 1 to be able to return the error in the calling function
            break;
        #if CONFIG_LIBUKSCHED
        case UK_FI_FAULT_DELAY:
            uk_pr_crit("Delay fault injected at %s:%d\n", site->file, site->line);
            uk_sched_thread_sleep(10000000); //sleeps for 10 milliseconds
            break;
        #endif
        default:
            break;
    }
    return 0; //returns 0 if no fault was injected, or if the fault was a delay so that the calling function can continue execution.
}

int uk_fi_hit(struct uk_fi_site *site){

    int to_return = 0;

    if (site->armed && site->inv >= site->trigger.n_invocations) {
        if(site->trigger.period > 0 && site->inv % site->trigger.period == 0){
            if(site->trigger.prob_on_100000 > 0 && site->trigger.prob_on_100000 <= 100000){
                unsigned long rand;
                uk_random_seed(fi_seed);
                rand %= 10000;
                if(rand <= site->trigger.prob_on_100000){
                    to_return = _uk_fi_hit(site);
                }
            }
        }
        else if(site->trigger.period <= 0){
            to_return = _uk_fi_hit(site);
        }        
    }

    return to_return;
}

2. devi considerare anche libname e non solo site (chiedi)
3. come devo inizializzare il seed? non ho capito. 
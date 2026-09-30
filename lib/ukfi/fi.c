#include <uk/fi.h>
#include <uk/libparam.h>
#include <uk/print.h>
#include <uk/config.h>
#include <uk/init.h>
#include <uk/assert.h>
#include <string.h>
#include <uk/sched.h>

static const char *fi_site = CONFIG_LIBUKFI_FI_SITE;
static unsigned fi_nop = CONFIG_LIBUKFI_FI_NOP;
static unsigned fi_prob = CONFIG_LIBUKFI_FI_PROB;
static unsigned fi_period = CONFIG_LIBUKFI_FI_PERIOD;
static int fi_fault = CONFIG_LIBUKFI_FI_FAULT;
static __u32 fi_seed = CONFIG_LIBUKFI_FI_SEED;
static __u32 fi_rnd_state;

UK_LIBPARAM_PARAM(fi_site, charp,"fault injection site");
UK_LIBPARAM_PARAM(fi_nop, uint,"Fire the fault on the n-th invocation of the operation");
UK_LIBPARAM_PARAM(fi_prob, uint,"Probability of triggering the fault");
UK_LIBPARAM_PARAM(fi_period, uint,"Periodicity of the fault injection");
UK_LIBPARAM_PARAM(fi_seed, __u32,"Random seed for fault injection");

static __u32 uk_fi_init_state(__u32 state, __u32 seed){
    //using the Knuth constant to generate the first random number to avoid obtaining zero as the 
    //first random number, which would cause the Marsaglia XOR shift algorithm to always return zero.
    state = seed * 2654435761u + 1; //the final u is to read the constant as unsigned
    if(state == 0)
        state = 1;
    return state;
}

static int uk_fi_init(struct uk_init_ctx * context __unused){
    struct uk_fi_site *itr;
    if(fi_nop == 0)
        fi_nop = 1; //default value
    if(fi_prob>100000)
        fi_prob = 100000; //default value                
    if(fi_seed == 0)
        fi_seed = 1; //default value
    fi_rnd_state = uk_fi_init_state(fi_rnd_state, fi_seed);
    //this makes the state the same for all sites. 
    //Future implementations will require the state to be in the site descriptor to be different for each site.
    uk_fi_foreach(itr, uk_fitab_start, uk_fitab_end){
        if(fi_site[0]!='\0' && !strcmp(itr->site, fi_site)){
            if(fi_fault >= UK_FI_FAULT_MAX || fi_fault < 0){
                itr->armed = UK_FI_DISARMED;
                uk_pr_warn("fault selected was not available, disarming site %s:%s", itr->libname, itr->site);
            }else if(fi_fault == UK_FI_FAULT_ERROR && !itr->can_fail){
                itr->armed = UK_FI_DISARMED;
                uk_pr_warn("returning an error value is not possible for the site %s:%s, disarming.", itr->libname, itr->site);
            }else{
                itr->armed = UK_FI_ARMED;
                itr->inv = 0;                   
                itr->trigger.period = fi_period;
                itr->trigger.prob_on_100000 = fi_prob;
                itr->trigger.n_invocations = fi_nop;
                itr->faulttype = fi_fault;
            }
        }
        uk_pr_info("Fault injection site: %s:%s in file %s:%d, armed=%d, inv=%lu, trigger.n_invocations=%u\n",
            itr->libname, itr->site, itr->file, itr->line, itr->armed, itr->inv, itr->trigger.n_invocations);
    }
    return 0;

}

uk_early_initcall(uk_fi_init, 0x0);
//the second parameter is 0x0 because NULL expands to (void*)0 and the function crashes seeing the parenthesis character.
//0x0 expands to uk_inittab9_uk_fi_init_0x0, which is a valid identifier and doesn't cause any issues.

static __u32 uk_fi_next_state(__u32 state){
    //using the Marsaglia XOR shift algorithm to generate a random number
    //we don't need to defend against race conditions since the scheduler is not preemptive and we work on a single cpu
    state ^= state << 13;
    state ^= state >> 17;
    state ^= state << 5;
    return state;
}

int _uk_fi_hit(struct uk_fi_site *site){
    switch(site->faulttype){
        case UK_FI_FAULT_CRASH:
            //crashes and doesn't return anything, so we don't need to return a value here
            UK_CRASH("Crash fault injected at %s:%d\n", site->file, site->line);
            break;
        case UK_FI_FAULT_HANG:
            //hangs and doesn't return anything, so we don't need to return a value here
            uk_pr_crit("Hang fault injected at %s:%d\n", site->file, site->line);
            while(1);
            break;
        case UK_FI_FAULT_ERROR:
            if(site->can_fail){
                uk_pr_crit("Error fault injected at %s:%d\n", site->file, site->line);
                return 1; //returning 1 to be able to return the error in the calling function
            }else{
                uk_pr_warn("Fault injection site %s:%s wants to return an error but can't\n", site->libname, site->site);
            }
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
        if((site->trigger.period > 0 && (site->inv - site->trigger.n_invocations) % site->trigger.period == 0) || site->trigger.period ==0){
            if(site->trigger.prob_on_100000==100000){
                to_return = _uk_fi_hit(site);
            }else{
                unsigned long rand;
                rand = fi_rnd_state%100000;
                fi_rnd_state = uk_fi_next_state(fi_rnd_state);
                if(rand < site->trigger.prob_on_100000){
                    to_return = _uk_fi_hit(site);
                }
            }
        }    
    }

    return to_return;
}